#include "pch.h"
#include "App.xaml.h"
#include "MainWindow.xaml.h"

namespace winrt::SurveyController::App::implementation
{
    App::App()
    {
#if defined _DEBUG && !defined DISABLE_XAML_GENERATED_BREAK_ON_UNHANDLED_EXCEPTION
        UnhandledException([](IInspectable const&, Microsoft::UI::Xaml::UnhandledExceptionEventArgs const& args)
        {
            if (IsDebuggerPresent())
            {
                auto message = args.Message();
                __debugbreak();
            }
        });
#endif
    }

    void App::OnLaunched(Microsoft::UI::Xaml::LaunchActivatedEventArgs const&)
    {
        m_window = make<MainWindow>();
        // Release the app-level window reference after the main window closes
        // so the desktop process can finish its shutdown promptly.
        m_window.Closed([this](IInspectable const&, Microsoft::UI::Xaml::WindowEventArgs const&)
        {
            m_window = nullptr;
        });
        m_window.Activate();
    }
}
