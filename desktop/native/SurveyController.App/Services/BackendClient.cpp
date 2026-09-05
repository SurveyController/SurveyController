#include "pch.h"
#include "BackendClient.h"
#include "JsonHelpers.h"

#include <condition_variable>
#include <filesystem>
#include <thread>

namespace winrt::SurveyController::App::Services
{
    namespace
    {
        constexpr std::uint32_t maxFrameSize = 16U << 20;

        [[noreturn]] void ThrowLastError(wchar_t const* operation)
        {
            throw winrt::hresult_error(HRESULT_FROM_WIN32(GetLastError()), operation);
        }
    }

    struct RpcSession
    {
        winrt::handle process;
        winrt::handle stdinWrite;
        winrt::handle stdoutRead;
        std::mutex ioMutex;
        std::mutex inFlightMutex;
        std::condition_variable inFlightChanged;
        std::size_t inFlight{};
        std::atomic_bool accepting{ true };
    };

    namespace
    {
        struct InFlightGuard
        {
            explicit InFlightGuard(std::shared_ptr<RpcSession> value) : session(std::move(value))
            {
                std::scoped_lock lock(session->inFlightMutex);
                if (!session->accepting.load())
                {
                    throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_SHUTDOWN_IN_PROGRESS), L"后端正在关闭");
                }
                ++session->inFlight;
            }

            ~InFlightGuard()
            {
                std::scoped_lock lock(session->inFlightMutex);
                --session->inFlight;
                session->inFlightChanged.notify_all();
            }

            std::shared_ptr<RpcSession> session;
        };
    }

    BackendClient& BackendClient::Current()
    {
        static BackendClient client;
        return client;
    }

    BackendClient::~BackendClient()
    {
        ShutdownImmediate();
    }

    BackendState BackendClient::State() const noexcept
    {
        std::scoped_lock lock(m_stateMutex);
        return m_state;
    }

    void BackendClient::Start()
    {
        {
            std::unique_lock lock(m_stateMutex);
            m_stateChanged.wait(lock, [&] { return m_state != BackendState::Starting; });
            if (m_state == BackendState::Running)
            {
                if (m_session && WaitForSingleObject(m_session->process.get(), 0) == WAIT_TIMEOUT) return;
                m_session.reset();
                m_state = BackendState::Stopped;
            }
            if (m_state == BackendState::Starting)
                throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_BUSY), L"后端正在启动");
            if (m_state == BackendState::Stopping)
                throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_SHUTDOWN_IN_PROGRESS), L"后端正在关闭");
            m_state = BackendState::Starting;
        }

        std::shared_ptr<RpcSession> session;
        try { session = CreateSession(); }
        catch (...)
        {
            std::scoped_lock lock(m_stateMutex);
            m_state = BackendState::Stopped;
            m_stateChanged.notify_all();
            throw;
        }

        std::scoped_lock lock(m_stateMutex);
        if (m_state != BackendState::Starting)
        {
            session->accepting.store(false);
            TerminateProcess(session->process.get(), ERROR_PROCESS_ABORTED);
            m_stateChanged.notify_all();
            throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_CANCELLED), L"后端启动已取消");
        }
        m_session = std::move(session);
        m_state = BackendState::Running;
        m_stateChanged.notify_all();
    }

    std::shared_ptr<RpcSession> BackendClient::AcquireSession()
    {
        for (;;)
        {
            {
                std::scoped_lock lock(m_stateMutex);
                if (m_state == BackendState::Running && m_session)
                {
                    if (WaitForSingleObject(m_session->process.get(), 0) == WAIT_TIMEOUT) return m_session;
                    m_session->accepting.store(false);
                    m_session.reset();
                    m_state = BackendState::Stopped;
                }
                if (m_state == BackendState::Stopping)
                    throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_SHUTDOWN_IN_PROGRESS), L"后端正在关闭");
            }
            Start();
        }
    }

    void BackendClient::MarkSessionFailed(std::shared_ptr<RpcSession> const& session) noexcept
    {
        session->accepting.store(false);
        if (session->process) TerminateProcess(session->process.get(), ERROR_PROCESS_ABORTED);
        std::scoped_lock lock(m_stateMutex);
        if (m_session == session && m_state == BackendState::Running)
        {
            m_session.reset();
            m_state = BackendState::Stopped;
            m_stateChanged.notify_all();
        }
    }

    void BackendClient::ShutdownImmediate() noexcept
    {
        std::shared_ptr<RpcSession> session;
        {
            std::scoped_lock lock(m_stateMutex);
            if (m_state == BackendState::Stopped) return;
            m_state = BackendState::Stopping;
            session = m_session;
            if (session) session->accepting.store(false);
        }

        if (session)
        {
            session->stdinWrite.close();
            if (session->process && WaitForSingleObject(session->process.get(), 0) == WAIT_TIMEOUT)
            {
                TerminateProcess(session->process.get(), ERROR_PROCESS_ABORTED);
                // TerminateProcess is asynchronous; wait before releasing the
                // handle so the next preview can safely replace the backend exe.
                WaitForSingleObject(session->process.get(), 2000);
            }

            std::unique_lock lock(session->inFlightMutex);
            session->inFlightChanged.wait_for(lock, std::chrono::seconds{ 2 }, [&] { return session->inFlight == 0; });
            lock.unlock();
            session->stdoutRead.close();
            session->process.close();
        }

        std::scoped_lock lock(m_stateMutex);
        m_session.reset();
        m_state = BackendState::Stopped;
        m_stateChanged.notify_all();
    }

    hstring BackendClient::Call(hstring const& method, hstring const& params, std::chrono::milliseconds timeout)
    {
        if (timeout <= std::chrono::milliseconds::zero())
            throw winrt::hresult_error(E_INVALIDARG, L"RPC 超时时间无效");

        auto session = AcquireSession();
        InFlightGuard inFlight{ session };
        std::scoped_lock ioLock(session->ioMutex);
        if (!session->accepting.load())
            throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_SHUTDOWN_IN_PROGRESS), L"后端正在关闭");

        auto const requestId = m_nextRequestId.fetch_add(1);
        auto const payload = BuildRequestPayload(requestId, method, params);
        auto const requestSize = static_cast<std::uint32_t>(payload.size());

        std::mutex timerMutex;
        std::condition_variable timerChanged;
        bool completed = false;
        std::atomic_bool timedOut = false;
        std::thread watchdog([session, timeout, &timerMutex, &timerChanged, &completed, &timedOut]
        {
            std::unique_lock lock(timerMutex);
            if (!timerChanged.wait_for(lock, timeout, [&] { return completed; }))
            {
                timedOut.store(true);
                session->accepting.store(false);
                if (session->process) TerminateProcess(session->process.get(), ERROR_TIMEOUT);
            }
        });
        auto finishWatchdog = [&]
        {
            { std::scoped_lock lock(timerMutex); completed = true; }
            timerChanged.notify_one();
            watchdog.join();
        };

        try
        {
            WriteExact(session->stdinWrite.get(), &requestSize, sizeof(requestSize));
            WriteExact(session->stdinWrite.get(), payload.data(), requestSize);
            std::uint32_t responseSize = 0;
            ReadExact(session->stdoutRead.get(), &responseSize, sizeof(responseSize));
            if (responseSize == 0 || responseSize > maxFrameSize)
                throw winrt::hresult_error(E_FAIL, L"RPC 响应大小无效");
            std::string responsePayload(responseSize, '\0');
            ReadExact(session->stdoutRead.get(), responsePayload.data(), responseSize);
            finishWatchdog();
            if (timedOut.load())
            {
                MarkSessionFailed(session);
                throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_TIMEOUT), L"后端响应超时");
            }
            return ParseResponsePayload(requestId, responsePayload);
        }
        catch (...)
        {
            finishWatchdog();
            MarkSessionFailed(session);
            if (timedOut.load())
                throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_TIMEOUT), L"后端响应超时");
            throw;
        }
    }

    Windows::Foundation::IAsyncOperation<hstring> BackendClient::CallAsync(
        hstring method, hstring params, std::chrono::milliseconds timeout)
    {
        co_await winrt::resume_background();
        co_return Call(method, params, timeout);
    }

    std::string BackendClient::BuildRequestPayload(std::uint64_t requestId, hstring const& method, hstring const& params)
    {
        if (method.empty()) throw winrt::hresult_error(E_INVALIDARG, L"RPC 方法不能为空");
        Windows::Data::Json::JsonObject request;
        request.Insert(L"id", Windows::Data::Json::JsonValue::CreateNumberValue(static_cast<double>(requestId)));
        request.Insert(L"method", Windows::Data::Json::JsonValue::CreateStringValue(method));
        try { request.Insert(L"params", Windows::Data::Json::JsonValue::Parse(params)); }
        catch (winrt::hresult_error const&) { throw winrt::hresult_error(E_INVALIDARG, L"RPC 参数不是有效 JSON"); }
        auto payload = winrt::to_string(request.Stringify());
        if (payload.empty() || payload.size() > maxFrameSize)
            throw winrt::hresult_error(E_INVALIDARG, L"RPC 请求大小无效");
        return payload;
    }

    hstring BackendClient::ParseResponsePayload(std::uint64_t requestId, std::string const& payload)
    {
        Windows::Data::Json::JsonObject response;
        hstring parseError;
        if (!TryParseJsonObject(winrt::to_hstring(payload), response, parseError))
            throw winrt::hresult_error(E_FAIL, L"RPC 响应不是有效 JSON：" + parseError);
        if (!response.HasKey(L"id") || response.GetNamedValue(L"id").ValueType() != Windows::Data::Json::JsonValueType::Number)
            throw winrt::hresult_error(E_FAIL, L"RPC 响应缺少有效 id");
        if (static_cast<std::uint64_t>(response.GetNamedNumber(L"id")) != requestId)
            throw winrt::hresult_error(E_FAIL, L"RPC 响应编号不匹配");
        auto const hasResult = response.HasKey(L"result");
        auto const hasError = response.HasKey(L"error");
        if (!hasResult && !hasError)
            throw winrt::hresult_error(E_FAIL, L"RPC 响应缺少 result 或 error");
        if (hasError)
        {
            auto value = response.GetNamedValue(L"error");
            if (value.ValueType() != Windows::Data::Json::JsonValueType::Null)
            {
                if (value.ValueType() != Windows::Data::Json::JsonValueType::Object)
                    throw winrt::hresult_error(E_FAIL, L"RPC error 字段类型无效");
                auto error = value.GetObject();
                if (!error.HasKey(L"message") || error.GetNamedValue(L"message").ValueType() != Windows::Data::Json::JsonValueType::String)
                    throw winrt::hresult_error(E_FAIL, L"RPC error 缺少有效 message");
                throw winrt::hresult_error(E_FAIL, error.GetNamedString(L"message"));
            }
        }
        if (!hasResult) throw winrt::hresult_error(E_FAIL, L"RPC 成功响应缺少 result");
        return response.GetNamedValue(L"result").Stringify();
    }

    std::shared_ptr<RpcSession> BackendClient::CreateSession()
    {
        auto session = std::make_shared<RpcSession>();
        SECURITY_ATTRIBUTES security{ sizeof(security), nullptr, TRUE };
        winrt::handle childStdinRead, childStdoutWrite, childStderr;
        if (!CreatePipe(childStdinRead.put(), session->stdinWrite.put(), &security, 0) ||
            !CreatePipe(session->stdoutRead.put(), childStdoutWrite.put(), &security, 0))
            ThrowLastError(L"创建后端管道失败");
        if (!SetHandleInformation(session->stdinWrite.get(), HANDLE_FLAG_INHERIT, 0) ||
            !SetHandleInformation(session->stdoutRead.get(), HANDLE_FLAG_INHERIT, 0))
            ThrowLastError(L"配置后端管道失败");
        childStderr.attach(CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
        if (!childStderr) ThrowLastError(L"打开后端错误输出失败");

        SIZE_T attributeBytes = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &attributeBytes);
        std::vector<std::byte> storage(attributeBytes);
        auto attributes = reinterpret_cast<PPROC_THREAD_ATTRIBUTE_LIST>(storage.data());
        if (!InitializeProcThreadAttributeList(attributes, 1, 0, &attributeBytes))
            ThrowLastError(L"初始化后端句柄列表失败");
        struct Guard { PPROC_THREAD_ATTRIBUTE_LIST value; ~Guard() { DeleteProcThreadAttributeList(value); } } guard{ attributes };
        std::array<HANDLE, 3> inherited{ childStdinRead.get(), childStdoutWrite.get(), childStderr.get() };
        if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
            inherited.data(), sizeof(inherited), nullptr, nullptr))
            ThrowLastError(L"限制后端继承句柄失败");

        STARTUPINFOEXW startup{};
        startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = childStdinRead.get();
        startup.StartupInfo.hStdOutput = childStdoutWrite.get();
        startup.StartupInfo.hStdError = childStderr.get();
        startup.lpAttributeList = attributes;
        auto path = BackendPath();
        auto commandLine = L"\"" + path + L"\"";
        PROCESS_INFORMATION process{};
        if (!CreateProcessW(path.c_str(), commandLine.data(), nullptr, nullptr, TRUE,
            EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW, nullptr, nullptr, &startup.StartupInfo, &process))
            ThrowLastError(L"启动 SurveyController 后端失败");
        CloseHandle(process.hThread);
        session->process.attach(process.hProcess);
        return session;
    }

    std::wstring BackendClient::BackendPath()
    {
        std::wstring modulePath(32768, L'\0');
        auto length = GetModuleFileNameW(nullptr, modulePath.data(), static_cast<DWORD>(modulePath.size()));
        if (length == 0 || length == modulePath.size()) ThrowLastError(L"读取应用路径失败");
        modulePath.resize(length);
        return (std::filesystem::path(modulePath).parent_path() / L"SurveyController.Backend.exe").wstring();
    }

    void BackendClient::ReadExact(HANDLE handle, void* buffer, std::uint32_t size)
    {
        auto bytes = static_cast<std::byte*>(buffer);
        for (std::uint32_t offset = 0; offset < size;)
        {
            DWORD read = 0;
            if (!ReadFile(handle, bytes + offset, size - offset, &read, nullptr)) ThrowLastError(L"读取后端响应失败");
            if (read == 0) throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_BROKEN_PIPE), L"后端响应提前结束");
            offset += read;
        }
    }

    void BackendClient::WriteExact(HANDLE handle, void const* buffer, std::uint32_t size)
    {
        auto bytes = static_cast<std::byte const*>(buffer);
        for (std::uint32_t offset = 0; offset < size;)
        {
            DWORD written = 0;
            if (!WriteFile(handle, bytes + offset, size - offset, &written, nullptr)) ThrowLastError(L"写入后端请求失败");
            if (written == 0) throw winrt::hresult_error(HRESULT_FROM_WIN32(ERROR_WRITE_FAULT), L"后端请求未写入");
            offset += written;
        }
    }
}
