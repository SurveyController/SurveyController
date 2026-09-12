#include "pch.h"
#include "TaskPage.xaml.h"
#include "Services/RpcServices.h"
#include "Services/NativeResource.h"
#include "Services/JsonHelpers.h"
#include "Services/TaskNotification.h"
#include "Services/WindowContext.h"

#include <algorithm>

namespace winrt::SurveyController::App::implementation
{
    namespace
    {
        using namespace Microsoft::UI::Xaml;
        using namespace Microsoft::UI::Xaml::Controls;
        using namespace Windows::Data::Json;

        hstring EscapeRunJsonString(hstring const& value)
        {
            return JsonValue::CreateStringValue(value).Stringify();
        }

        InfoBarSeverity RunSeverity(hstring const& status)
        {
            if (status == L"succeeded") return InfoBarSeverity::Success;
            if (status == L"paused") return InfoBarSeverity::Warning;
            if (status == L"failed") return InfoBarSeverity::Error;
            return InfoBarSeverity::Informational;
        }
    }

    fire_and_forget TaskPage::OnPauseRun(IInspectable const&, RoutedEventArgs const&)
    {
        auto lifetime = get_strong();
        try { co_await RunControlAsync(L"PauseRun", L"{\"value\":\"用户暂停\"}"); }
        catch (hresult_error const& error) { SetFooterError(error.message()); }
        catch (...) { SetFooterError(L"暂停任务失败。"); }
    }

    fire_and_forget TaskPage::OnResumeRun(IInspectable const&, RoutedEventArgs const&)
    {
        auto lifetime = get_strong();
        try { co_await RunControlAsync(L"ResumeRun", L"null"); }
        catch (hresult_error const& error) { SetFooterError(error.message()); }
        catch (...) { SetFooterError(L"恢复任务失败。"); }
    }

    fire_and_forget TaskPage::OnStopRun(IInspectable const&, RoutedEventArgs const&)
    {
        auto lifetime = get_strong();
        try { co_await RunControlAsync(L"CancelRun", L"null"); }
        catch (hresult_error const& error) { SetFooterError(error.message()); }
        catch (...) { SetFooterError(L"停止任务失败。"); }
    }

    fire_and_forget TaskPage::OnExportLogs(IInspectable const&, RoutedEventArgs const&)
    {
        auto lifetime = get_strong();
        try
        {
            auto path = co_await ChooseSaveFile(false);
            if (path.empty()) co_return;
            JsonArray lines;
            for (auto const& line : m_logLines) lines.Append(JsonValue::CreateStringValue(line));
            co_await ExportLinesAsync(path, lines, L"日志已导出");
        }
        catch (hresult_error const& error) { SetFooterError(error.message()); }
        catch (...) { SetFooterError(L"导出日志失败。"); }
    }

    fire_and_forget TaskPage::OnExportResult(IInspectable const&, RoutedEventArgs const&)
    {
        auto lifetime = get_strong();
        if (!m_runResult) co_return;
        try
        {
            auto path = co_await ChooseSaveFile(true);
            if (path.empty()) co_return;
            JsonObject payload;
            payload.SetNamedValue(L"result", m_runResult);
            JsonArray logs;
            for (auto const& line : m_logLines) logs.Append(JsonValue::CreateStringValue(line));
            payload.SetNamedValue(L"logs", logs);
            JsonArray lines;
            lines.Append(JsonValue::CreateStringValue(payload.Stringify()));
            co_await ExportLinesAsync(path, lines, L"任务结果已导出");
        }
        catch (hresult_error const& error) { SetFooterError(error.message()); }
        catch (...) { SetFooterError(L"导出任务结果失败。"); }
    }

    Windows::Foundation::IAsyncOperation<hstring> TaskPage::ChooseSaveFile(bool json)
    {
        Microsoft::Windows::Storage::Pickers::FileSavePicker picker(Services::MainWindowId());
        picker.SuggestedFileName(json ? L"surveycontroller-result" : L"surveycontroller-runtime");
        picker.DefaultFileExtension(json ? L".json" : L".log");
        auto choices = picker.FileTypeChoices();
        Windows::Foundation::Collections::IVector<hstring> extensions = winrt::single_threaded_vector<hstring>();
        extensions.Append(json ? L".json" : L".log");
        choices.Insert(json ? L"JSON 文件" : L"日志文件", extensions);
        auto file = co_await picker.PickSaveFileAsync();
        co_return file ? file.Path() : hstring{};
    }

    Windows::Foundation::IAsyncAction TaskPage::ExportLinesAsync(hstring const& path, JsonArray const& lines, hstring const& successMessage)
    {
        auto lifetime = get_strong();
        JsonObject request;
        request.SetNamedValue(L"path", JsonValue::CreateStringValue(path));
        request.SetNamedValue(L"lines", lines);
        auto dispatcher = DispatcherQueue();
        hstring error;
        co_await resume_background();
        try { co_await Services::TaskService{}.ExportAsync(path, lines); }
        catch (hresult_error const& value) { error = value.message(); }
        dispatcher.TryEnqueue([lifetime, error, successMessage]()
        {
            lifetime->RunExportStatus().Severity(error.empty() ? InfoBarSeverity::Success : InfoBarSeverity::Error);
            lifetime->RunExportStatus().Title(error.empty() ? successMessage : L"导出失败");
            lifetime->RunExportStatus().Message(error);
            lifetime->RunExportStatus().IsOpen(true);
        });
    }

    void TaskPage::ApplyRunState(hstring const& json)
    {
        JsonObject state;
        hstring error;
        if (!Services::TryParseJsonObject(json, state, error))
        {
            SetFooterError(error);
            return;
        }
        auto nextRunId = state.GetNamedString(L"runId", m_runId);
        if (!nextRunId.empty() && nextRunId != m_runId)
        {
            RunLogs().Items().Clear();
            m_logLines.clear();
            m_runResult = nullptr;
            RunResultCard().Visibility(Microsoft::UI::Xaml::Visibility::Collapsed);
            ExportResultButton().Visibility(Microsoft::UI::Xaml::Visibility::Collapsed);
            ExportLogsButton().Visibility(Microsoft::UI::Xaml::Visibility::Collapsed);
            RunExportStatus().IsOpen(false);
        }
        m_runId = nextRunId;
        m_afterSequence = static_cast<uint64_t>(state.GetNamedNumber(L"nextSequence", static_cast<double>(m_afterSequence)));
        auto status = state.GetNamedString(L"status", L"idle");
        auto runTitle = status == L"running" ? L"运行中" : status == L"paused" ? L"已暂停" : status == L"succeeded" ? L"已完成" : status == L"failed" ? L"运行失败" : status == L"canceling" ? L"正在停止" : status == L"stopped" ? L"已停止" : L"尚未启动";
        RunStatus().Title(runTitle);
        RunStatus().Severity(RunSeverity(status));
        auto events = state.GetNamedArray(L"events", JsonArray{});
        for (auto const& value : events)
        {
            auto event = value.GetObject().GetNamedObject(L"event", JsonObject{});
            auto message = event.GetNamedString(L"message", L"");
            if (!message.empty())
            {
                auto worker = event.GetNamedString(L"worker", L"core");
                hstring line{ L"[" + std::wstring{ worker } + L"] " + std::wstring{ message } };
                m_logLines.push_back(line);
                if (m_logLines.size() > 200) m_logLines.erase(m_logLines.begin());
                RunLogs().Items().Append(box_value(line));
                if (RunLogs().Items().Size() > 200) RunLogs().Items().RemoveAt(0);
            }
            auto total = event.GetNamedNumber(L"total", 0);
            auto current = event.GetNamedNumber(L"current", 0);
            if (total > 0)
            {
                RunProgress().Maximum(total);
                RunProgress().Value((std::min)(current, total));
                RunProgressText().Text(hstring{ std::to_wstring(static_cast<int32_t>(current)) + L" / " + std::to_wstring(static_cast<int32_t>(total)) });
            }
            if (!message.empty()) RunStatus().Message(message);
        }
        m_runResult = state.GetNamedObject(L"result", JsonObject{});
        if (m_runResult && m_runResult.Size() > 0)
        {
            auto success = static_cast<int32_t>(m_runResult.GetNamedNumber(L"success", 0));
            auto fail = static_cast<int32_t>(m_runResult.GetNamedNumber(L"fail", 0));
            RunResultSuccess().Text(hstring{ std::to_wstring(success) });
            RunResultFail().Text(hstring{ std::to_wstring(fail) });
            RunResultTotal().Text(hstring{ std::to_wstring(success + fail) });
            RunResultCard().Visibility(Microsoft::UI::Xaml::Visibility::Visible);
            ExportResultButton().Visibility(Microsoft::UI::Xaml::Visibility::Visible);
        }
        ExportLogsButton().Visibility(m_logLines.empty()
            ? Microsoft::UI::Xaml::Visibility::Collapsed : Microsoft::UI::Xaml::Visibility::Visible);
        auto stateError = state.GetNamedString(L"error", L"");
        if (!stateError.empty()) RunStatus().Message(stateError);
        auto active = status == L"running" || status == L"paused" || status == L"canceling";
        if (!active && !m_runId.empty() && m_notifiedRunId != m_runId &&
            (!m_settings || m_settings.GetNamedBoolean(L"taskResultNotification", true)) &&
            (m_runResult || !stateError.empty()))
        {
            auto title = stateError.empty() ? L"任务执行完成" : L"任务执行失败";
            auto body = stateError;
            if (body.empty())
            {
                auto success = static_cast<int32_t>(m_runResult.GetNamedNumber(L"success", 0));
                auto fail = static_cast<int32_t>(m_runResult.GetNamedNumber(L"fail", 0));
                body = hstring{ L"成功 " + std::to_wstring(success) + L" 份，失败 " + std::to_wstring(fail) + L" 份" };
            }
            Services::TaskNotification::Current().Show(title, body);
            m_notifiedRunId = m_runId;
        }
        PauseButton().IsEnabled(status == L"running");
        ResumeButton().IsEnabled(status == L"paused");
        StopButton().IsEnabled(active && status != L"canceling");
        PrimaryButton().IsEnabled(!active && !m_busy);
        if (!active && m_pollTimer) m_pollTimer.Stop();
    }

    void TaskPage::StartPolling()
    {
        if (!m_isLoaded || m_runId.empty()) return;
        if (!m_pollTimer)
        {
            m_pollTimer = DispatcherQueue().CreateTimer();
            m_pollTimer.Interval(std::chrono::milliseconds(700));
            m_pollTimer.Tick([weak = get_weak()](auto const&, auto const&)
            {
                if (auto self = weak.get()) self->PollRunAsync();
            });
        }
        m_pollFailures = 0;
        m_pollTimer.Interval(std::chrono::milliseconds(700));
        m_pollTimer.Start();
    }

    void TaskPage::StopPolling() noexcept
    {
        if (m_pollTimer) m_pollTimer.Stop();
        m_polling = false;
    }

    Windows::Foundation::IAsyncAction TaskPage::PollRunAsync()
    {
        auto lifetime = get_strong();
        if (m_polling || m_runId.empty() || !m_isLoaded) co_return;
        m_polling = true;
        auto const generation = m_pageGeneration;
        auto const runId = m_runId;
        hstring result, error;
        try { result = co_await Services::TaskService{}.StateAsync(runId, m_afterSequence); }
        catch (hresult_error const& value) { error = value.message(); }
        catch (std::exception const& value) { error = to_hstring(value.what()); }
        catch (...) { error = L"查询任务状态失败。"; }
        if (!m_isLoaded || generation != m_pageGeneration || runId != m_runId)
        {
            // The stale request must release the guard, otherwise a later poll is blocked forever.
            m_polling = false;
            co_return;
        }
        m_polling = false;
        if (!error.empty())
        {
            ++m_pollFailures;
            if (m_pollFailures >= 3)
            {
                StopPolling();
                SetFooterError(L"后端连接已中断,请重新进入任务页后重试：" + error);
                co_return;
            }
            auto backoff = (std::min)(1 << m_pollFailures, 8);
            m_pollTimer.Interval(std::chrono::milliseconds(700 * backoff));
            co_return;
        }
        m_pollFailures = 0;
        m_pollTimer.Interval(std::chrono::milliseconds(700));
        ApplyRunState(result);
    }

    Windows::Foundation::IAsyncAction TaskPage::RunControlAsync(hstring method, hstring params)
    {
        auto lifetime = get_strong();
        if (m_busy) co_return;
        SetBusy(true, L"正在更新任务状态");
        hstring result, error;
        try
        {
            if (method == L"PauseRun") result = co_await Services::TaskService{}.PauseAsync(L"用户暂停");
            else if (method == L"ResumeRun") result = co_await Services::TaskService{}.ResumeAsync();
            else if (method == L"CancelRun") result = co_await Services::TaskService{}.StopAsync();
            else throw hresult_error(E_INVALIDARG, L"不支持的任务控制操作");
        }
        catch (hresult_error const& value) { error = value.message(); }
        catch (std::exception const& value) { error = to_hstring(value.what()); }
        catch (...) { error = L"更新任务状态失败。"; }
        SetBusy(false);
        if (!error.empty()) { SetFooterError(error); co_return; }
        ApplyRunState(result);
    }
}
