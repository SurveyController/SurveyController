#include "pch.h"
#include "MainWindow.xaml.h"
#include "Services/WindowContext.h"
#include "Views/TaskPage.xaml.h"
#include "Views/ReverseFillPage.xaml.h"
#include "Views/SettingsPage.xaml.h"
#include "Views/CommunityPage.xaml.h"
#include "Views/MorePage.xaml.h"
#include "Services/BackendClient.h"
#include "Services/RpcServices.h"
#include "Services/JsonHelpers.h"
#include "Services/ShellSettings.h"
#include "Services/WizardDocument.h"
#include "Services/DialogStyling.h"

#if __has_include("MainWindow.g.cpp")
#include "MainWindow.g.cpp"
#endif

#include <microsoft.ui.xaml.window.h>
#include <winrt/Microsoft.UI.Interop.h>

namespace
{
    winrt::hstring ApplicationIconPath()
    {
        std::wstring modulePath(32768, L'\0');
        auto const length = ::GetModuleFileNameW(nullptr, modulePath.data(), static_cast<DWORD>(modulePath.size()));
        if (length == 0 || length == modulePath.size())
        {
            return {};
        }

        modulePath.resize(length);
        auto const separator = modulePath.find_last_of(L"\\/");
        if (separator == std::wstring::npos)
        {
            return {};
        }

        modulePath.resize(separator + 1);
        modulePath.append(L"Assets\\SurveyController.ico");
        return winrt::hstring{ modulePath };
    }
}

namespace winrt::SurveyController::App::implementation
{
    MainWindow::MainWindow()
    {
        InitializeComponent();
        Title(L"SurveyController");
        ConfigureTitleBar();
        ConfigureWindow();
        // Derive the id from the real HWND after the native window is available.
        Services::SetMainWindowId(Microsoft::UI::GetWindowIdFromWindow(m_hwnd));
        ConfigureBackdrop();
        Activated({ this, &MainWindow::OnWindowActivated });
        AppWindow().Closing({ this, &MainWindow::OnWindowClosing });
        Closed({ this, &MainWindow::OnWindowClosed });
        ShellNavigation().SelectionChanged({ this, &MainWindow::OnNavigationSelectionChanged });
    }

    void MainWindow::OnWindowActivated(IInspectable const&, Microsoft::UI::Xaml::WindowActivatedEventArgs const&)
    {
        if (!m_initializing && !m_initialized && !m_closing) InitializeAsync();
    }

    fire_and_forget MainWindow::InitializeAsync()
    {
        auto lifetime = get_strong();
        m_initializing = true;
        StartupStatus().Severity(Microsoft::UI::Xaml::Controls::InfoBarSeverity::Informational);
        StartupStatus().Title(L"正在启动后端");
        StartupStatus().Message(L"正在加载设置和配置。");
        StartupStatus().IsOpen(true);
        try
        {
            auto settings = co_await Services::SettingsService{}.LoadAsync();
            auto config = co_await Services::ConfigService{}.LoadAsync();
            if (m_closing) co_return;
            m_settingsJson = settings;
            m_configJson = config;
            Services::WizardDocument::Current().LoadConfigState(m_configJson);
            auto weak = get_weak();
            Services::ShellSettings::Current().SetChangedHandler([weak](hstring const& json)
            {
                if (auto self = weak.get()) self->ApplyShellSettings(json);
            });
            Services::ShellSettings::Current().Update(m_settingsJson);
            if (!m_hasNavigated) ShowPage(L"task");
            StartupStatus().IsOpen(false);
            m_initialized = true;
        }
        catch (hresult_error const& error)
        {
            StartupStatus().Severity(Microsoft::UI::Xaml::Controls::InfoBarSeverity::Error);
            StartupStatus().Title(L"后端启动失败");
            StartupStatus().Message(error.message());
        }
        catch (std::exception const& error)
        {
            StartupStatus().Severity(Microsoft::UI::Xaml::Controls::InfoBarSeverity::Error);
            StartupStatus().Title(L"初始化失败");
            StartupStatus().Message(to_hstring(error.what()));
        }
        catch (...)
        {
            StartupStatus().Severity(Microsoft::UI::Xaml::Controls::InfoBarSeverity::Error);
            StartupStatus().Title(L"初始化失败");
            StartupStatus().Message(L"发生未知错误。");
        }
        m_initializing = false;
    }

    void MainWindow::ConfigureBackdrop()
    {
        using namespace Microsoft::UI::Xaml::Media;
        if (IsWindows11OrGreater())
        {
            auto mica = MicaBackdrop{};
            mica.Kind(Microsoft::UI::Composition::SystemBackdrops::MicaKind::Base);
            SystemBackdrop(mica);
            return;
        }
        SystemBackdrop(DesktopAcrylicBackdrop{});
    }

    void MainWindow::ApplyShellSettings(hstring const& json)
    {
        using namespace Microsoft::UI::Xaml;
        using namespace Windows::Data::Json;

        JsonObject settings;
        hstring parseError;
        if (!Services::TryParseJsonObject(json, settings, parseError))
        {
            return;
        }
        auto theme = settings.GetNamedString(L"themeMode", L"system");
        auto root = Content().try_as<FrameworkElement>();
        if (root)
        {
            root.RequestedTheme(theme == L"light" ? ElementTheme::Light
                : theme == L"dark" ? ElementTheme::Dark : ElementTheme::Default);
        }
        ApplyTitleBarTheme(theme);

        ShellNavigation().PaneDisplayMode(settings.GetNamedBoolean(L"showNavigationText", true)
            ? Microsoft::UI::Xaml::Controls::NavigationViewPaneDisplayMode::Auto
            : Microsoft::UI::Xaml::Controls::NavigationViewPaneDisplayMode::LeftCompact);

        m_askSaveOnClose = settings.GetNamedBoolean(L"askSaveOnClose", true);
        auto topmost = settings.GetNamedBoolean(L"topmost", false);
        if (auto presenter = AppWindow().Presenter().try_as<Microsoft::UI::Windowing::OverlappedPresenter>())
        {
            presenter.IsAlwaysOnTop(topmost);
        }
    }

    void MainWindow::OnWindowClosing(
        Microsoft::UI::Windowing::AppWindow const&,
        Microsoft::UI::Windowing::AppWindowClosingEventArgs const& args)
    {
        if (m_closeConfirmed) return;
        m_closing = true;
        if (!m_askSaveOnClose) return;
        args.Cancel(true);
        if (!m_confirmingClose) ConfirmCloseAsync();
    }

    void MainWindow::OnWindowClosed(
        IInspectable const&,
        Microsoft::UI::Xaml::WindowEventArgs const&)
    {
        Services::BackendClient::Current().ShutdownImmediate();
    }

    fire_and_forget MainWindow::ConfirmCloseAsync()
    {
        auto lifetime = get_strong();
        m_confirmingClose = true;

        Microsoft::UI::Xaml::Controls::ContentDialog dialog;
        auto dialogThemeRevoker = Services::PrepareContentDialog(dialog, Content().XamlRoot());
        dialog.Title(box_value(L"保存当前配置？"));
        dialog.Content(box_value(L"关闭前可以把本次改动写入配置文件。"));
        dialog.PrimaryButtonText(L"保存并关闭");
        dialog.SecondaryButtonText(L"不保存并关闭");
        dialog.CloseButtonText(L"取消");
        dialog.DefaultButton(Microsoft::UI::Xaml::Controls::ContentDialogButton::Primary);

        auto result = co_await dialog.ShowAsync();
        if (result == Microsoft::UI::Xaml::Controls::ContentDialogResult::Primary)
        {
            hstring saveError;
            try
            {
                auto saved = co_await Services::ConfigService{}.SaveAsync(
                    Services::WizardDocument::Current().SaveRequest());
                Services::WizardDocument::Current().LoadConfigState(saved);
            }
            catch (hresult_error const& error) { saveError = error.message(); }
            catch (std::exception const& error) { saveError = to_hstring(error.what()); }
            catch (...) { saveError = L"保存配置失败。"; }

            if (!saveError.empty())
            {
                Microsoft::UI::Xaml::Controls::ContentDialog failure;
                auto failureThemeRevoker = Services::PrepareContentDialog(failure, Content().XamlRoot());
                failure.Title(box_value(L"无法保存配置"));
                failure.Content(box_value(saveError));
                failure.CloseButtonText(L"返回");
                co_await failure.ShowAsync();
                m_confirmingClose = false;
                m_closing = false;
                co_return;
            }
        }

        m_confirmingClose = false;
        if (result == Microsoft::UI::Xaml::Controls::ContentDialogResult::None)
        {
            m_closing = false;
            co_return;
        }
        m_closeConfirmed = true;
        if (auto taskPage = ContentFrame().Content().try_as<SurveyController::App::TaskPage>())
        {
            if (auto impl = winrt::get_self<SurveyController::App::implementation::TaskPage>(taskPage))
            {
                impl->PrepareForShutdown();
            }
        }
        Close();
    }

    void MainWindow::ConfigureTitleBar()
    {
        ExtendsContentIntoTitleBar(true);
        SetTitleBar(AppTitleBar());

        auto titleBar = AppWindow().TitleBar();
        titleBar.ButtonBackgroundColor(Windows::UI::Colors::Transparent());
        titleBar.ButtonInactiveBackgroundColor(Windows::UI::Colors::Transparent());
        ApplyTitleBarTheme(L"system");
    }

    void MainWindow::ApplyTitleBarTheme(hstring const& themeMode)
    {
        auto titleBar = AppWindow().TitleBar();
        if (!titleBar.IsCustomizationSupported()) return;

        auto root = Content().try_as<Microsoft::UI::Xaml::FrameworkElement>();
        auto const dark = themeMode == L"dark" ||
            (themeMode == L"system" && root && root.ActualTheme() == Microsoft::UI::Xaml::ElementTheme::Dark);
        auto const foreground = dark ? Windows::UI::Colors::White() : Windows::UI::Colors::Black();
        titleBar.ButtonForegroundColor(foreground);
        titleBar.ButtonHoverForegroundColor(foreground);
        titleBar.ButtonPressedForegroundColor(foreground);
        titleBar.ButtonInactiveForegroundColor(foreground);
    }

    void MainWindow::ConfigureWindow()
    {
        Microsoft::UI::Xaml::Window window = *this;
        window.as<::IWindowNative>()->get_WindowHandle(&m_hwnd);
        auto appWindow = AppWindow();
        auto const dpi = ::GetDpiForWindow(m_hwnd);
        if (auto const iconPath = ApplicationIconPath(); !iconPath.empty())
        {
            appWindow.SetIcon(iconPath);
        }

        if (auto presenter = appWindow.Presenter().try_as<Microsoft::UI::Windowing::OverlappedPresenter>())
        {
            presenter.PreferredMinimumWidth(::MulDiv(720, static_cast<int>(dpi), USER_DEFAULT_SCREEN_DPI));
            presenter.PreferredMinimumHeight(::MulDiv(560, static_cast<int>(dpi), USER_DEFAULT_SCREEN_DPI));
        }

        auto displayArea = Microsoft::UI::Windowing::DisplayArea::GetFromWindowId(
            appWindow.Id(), Microsoft::UI::Windowing::DisplayAreaFallback::Nearest);
        auto width = ::MulDiv(1180, static_cast<int>(dpi), USER_DEFAULT_SCREEN_DPI);
        auto height = ::MulDiv(720, static_cast<int>(dpi), USER_DEFAULT_SCREEN_DPI);
        if (displayArea)
        {
            auto workArea = displayArea.WorkArea();
            auto const maxWidth = workArea.Width > 64 ? workArea.Width - 64 : workArea.Width;
            auto const maxHeight = workArea.Height > 64 ? workArea.Height - 64 : workArea.Height;
            width = width < maxWidth ? width : maxWidth;
            height = height < maxHeight ? height : maxHeight;
            appWindow.Resize({ width, height });
            auto size = appWindow.Size();
            appWindow.Move({
                workArea.X + (workArea.Width - size.Width) / 2,
                workArea.Y + (workArea.Height - size.Height) / 2
            });
        }
        else
        {
            appWindow.Resize({ width, height });
        }
        ContentFrame().CacheSize(2);
    }

    bool MainWindow::IsWindows11OrGreater()
    {
        OSVERSIONINFOEXW version{};
        version.dwOSVersionInfoSize = sizeof(version);
        version.dwBuildNumber = 22000;
        auto mask = VerSetConditionMask(0, VER_BUILDNUMBER, VER_GREATER_EQUAL);
        return VerifyVersionInfoW(&version, VER_BUILDNUMBER, mask) != FALSE;
    }

    void MainWindow::OnNavigationSelectionChanged(
        Microsoft::UI::Xaml::Controls::NavigationView const&,
        Microsoft::UI::Xaml::Controls::NavigationViewSelectionChangedEventArgs const& args)
    {
        if (!m_initialized || m_closing) return;
        auto item = args.SelectedItem().try_as<Microsoft::UI::Xaml::Controls::NavigationViewItem>();
        if (!item)
        {
            return;
        }
        auto tag = unbox_value_or<hstring>(item.Tag(), L"");
        ShowPage(tag);
    }

    void MainWindow::ShowPage(hstring const& tag)
    {
        using namespace Microsoft::UI::Xaml::Media::Animation;

        int32_t const targetIndex = tag == L"task" ? 0 : tag == L"reversefill" ? 1 : tag == L"settings" ? 2 : tag == L"community" ? 3 : 4;
        if (m_hasNavigated && targetIndex == m_currentPageIndex) return;

        NavigationTransitionInfo transition = EntranceNavigationTransitionInfo{};

        if (tag == L"reversefill")
        {
            ContentFrame().Navigate(xaml_typename<SurveyController::App::ReverseFillPage>(), nullptr, transition);
        }
        else if (tag == L"settings")
        {
            ContentFrame().Navigate(xaml_typename<SurveyController::App::SettingsPage>(), nullptr, transition);
        }
        else if (tag == L"community")
        {
            ContentFrame().Navigate(xaml_typename<SurveyController::App::CommunityPage>(), nullptr, transition);
        }
        else if (tag == L"more")
        {
            ContentFrame().Navigate(xaml_typename<SurveyController::App::MorePage>(), nullptr, transition);
        }
        else
        {
            ContentFrame().Navigate(xaml_typename<SurveyController::App::TaskPage>(), nullptr, transition);
        }
        m_currentPageIndex = targetIndex;
        m_hasNavigated = true;
    }
}
