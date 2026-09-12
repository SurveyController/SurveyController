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
        // WinUI 生命周期保证窗口关闭先于 App 析构，此处捕获 this 安全
        m_window.Closed([this](IInspectable const&, Microsoft::UI::Xaml::WindowEventArgs const&)
        {
            m_window = nullptr;
        });
        m_window.Activate();
    }
}
