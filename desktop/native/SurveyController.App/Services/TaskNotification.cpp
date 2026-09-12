#include "pch.h"
#include "TaskNotification.h"

namespace winrt::SurveyController::App::Services
{
    namespace
    {
        hstring EscapeXml(hstring const& value)
        {
            std::wstring escaped;
            escaped.reserve(value.size());
            for (auto const character : value)
            {
                switch (character)
                {
                case L'&': escaped += L"&amp;"; break;
                case L'<': escaped += L"&lt;"; break;
                case L'>': escaped += L"&gt;"; break;
                case L'\"': escaped += L"&quot;"; break;
                case L'\'': escaped += L"&apos;"; break;
                default: escaped += character; break;
                }
            }
            return hstring{ escaped };
        }
    }

    TaskNotification& TaskNotification::Current()
    {
        static TaskNotification instance;
        return instance;
    }

    bool TaskNotification::Show(hstring const& title, hstring const& body) noexcept
    {
        try
        {
            if (!EnsureRegistered()) return false;
            auto payload = hstring{
                L"<toast><visual><binding template=\"ToastGeneric\"><text>" +
                std::wstring{ EscapeXml(title) } + L"</text><text>" +
                std::wstring{ EscapeXml(body) } + L"</text></binding></visual></toast>"
            };
            auto notification = Microsoft::Windows::AppNotifications::AppNotification{ payload };
            Microsoft::Windows::AppNotifications::AppNotificationManager::Default().Show(notification);
            return true;
        }
        catch (...)
        {
            return false;
        }
    }

    bool TaskNotification::EnsureRegistered()
    {
        if (m_registered) return true;
        try
        {
            auto manager = Microsoft::Windows::AppNotifications::AppNotificationManager::Default();
            m_invokedToken = manager.NotificationInvoked([](auto const&, auto const&) {});
            manager.Register();
            m_registered = true;
            return true;
        }
        catch (...)
        {
            return false;
        }
    }

    TaskNotification::~TaskNotification()
    {
        if (!m_registered) return;
        try
        {
            auto manager = Microsoft::Windows::AppNotifications::AppNotificationManager::Default();
            manager.NotificationInvoked(m_invokedToken);
            manager.Unregister();
        }
        catch (...)
        {
        }
    }
}
