#include "pch.h"
#include "TaskPage.xaml.h"

namespace winrt::SurveyController::App::implementation
{
    using namespace Microsoft::UI::Xaml;
    using namespace Microsoft::UI::Xaml::Controls;

    void TaskPage::OnSectionChanged(NavigationView const&, NavigationViewSelectionChangedEventArgs const& args)
    {
        if (!m_initialized || m_syncingNavigation) return;
        auto item = args.SelectedItem().try_as<NavigationViewItem>();
        if (!item) return;
        auto tag = unbox_value_or<hstring>(item.Tag(), L"");
        if (tag.size() != 1 || tag[0] < L'0' || tag[0] > L'6') return;
        auto next = static_cast<int32_t>(tag[0] - L'0');
        if (m_busy || m_runActive || (next > 0 && !m_parsed) || !SyncControlsToDocument())
        {
            UpdateStepVisuals();
            return;
        }
        MoveToStep(next, true);
    }

    void TaskPage::MoveToStep(int32_t step, bool force)
    {
        if (step < 0 || step > 6 || (!force && step > m_highestStep + 1)) return;
        if (step == 5 && !SyncControlsToDocument()) return;
        UpdateReview();
        m_step = step;
        m_highestStep = (std::max)(m_highestStep, step);
        m_errorStep = -1;
        FooterStatus().Text(L"");
        UpdateStepVisuals();
        if (m_step == 2) ScheduleRuleRefresh();
    }

    void TaskPage::UpdateStepVisuals()
    {
        std::array<UIElement, 7> panels{ SurveyPanel(), AnswersPanel(), RulesPanel(), NetworkPanel(), TimingPanel(), LaunchPanel(), RunPanel() };
        static const std::array<hstring, 7> labels{ L"问卷来源", L"答案配置", L"条件规则", L"网络与信度", L"时间与节奏", L"检查与启动", L"运行监控" };
        m_syncingNavigation = true;
        for (int32_t index = 0; index < 7; ++index)
        {
            panels[index].Visibility(index == m_step ? Visibility::Visible : Visibility::Collapsed);
            auto item = SectionNavigation().MenuItems().GetAt(index).as<NavigationViewItem>();
            item.IsEnabled(!m_busy && (!m_runActive || index == 6) && (index == 0 || m_parsed) && (index != 6 || !m_runId.empty()));
            item.Content(box_value(labels[index]));
            if (index == m_errorStep)
            {
                InfoBadge badge;
                badge.Value(-1);
                item.InfoBadge(badge);
            }
            else item.InfoBadge(nullptr);
            Automation::AutomationProperties::SetName(item, labels[index] + (index == m_errorStep ? L"，需要处理错误" : L""));
        }
        SectionNavigation().SelectedItem(SectionNavigation().MenuItems().GetAt(m_step));
        m_syncingNavigation = false;
        WorkspaceTitle().Text(m_parsed ? m_document.Title() : L"任务工作台");
        WorkspaceSummary().Text(m_parsed ? to_hstring(m_document.QuestionCount()) + L" 道题目  ·  " + labels[m_step] : L"导入问卷后，按需选择配置项目");
        NetworkStatus().IsOpen(m_step == 3 && !NetworkStatus().Title().empty());
        CheckStatus().IsOpen(m_step == 5 && !CheckStatus().Title().empty());
        RunStatus().IsOpen(m_step == 6);
        if (m_step != 0) SurveyStatus().IsOpen(false);
        if (m_step != 6) RunExportStatus().IsOpen(false);
        FooterBar().Visibility(m_step > 0 && m_step < 6 ? Visibility::Visible : Visibility::Collapsed);
        BusyProgress().Visibility(m_busy ? Visibility::Visible : Visibility::Collapsed);
        SurveyPrimaryLabel().Text(m_parsed ? L"打开配置" : L"解析问卷");
        SurveyPrimaryIcon().Symbol(m_parsed ? Symbol::Forward : Symbol::Refresh);
        SurveyPrimaryButton().IsEnabled(!m_busy);
        BackButton().IsEnabled(!m_busy && m_step > 0);
        PrimaryButtonLabel().Text(m_step == 5 ? L"检查并启动作答" : L"下一项");
        PrimaryButtonIcon().Symbol(m_step == 5 ? Symbol::Send : Symbol::Forward);
        Automation::AutomationProperties::SetName(PrimaryButton(), PrimaryButtonLabel().Text());
        PrimaryButton().IsEnabled(!m_busy);
    }

    void TaskPage::SetBusy(bool busy, hstring const& message)
    {
        m_busy = busy;
        if (busy) m_errorStep = -1;
        FooterStatus().Text(message);
        UpdateStepVisuals();
    }

    void TaskPage::SetFooterError(hstring const& message)
    {
        m_errorStep = m_step;
        FooterStatus().Text(message);
        auto status = m_step == 5 ? CheckStatus() : SurveyStatus();
        status.Title(m_step == 5 ? L"无法启动任务" : L"无法继续");
        status.Message(message);
        status.Severity(InfoBarSeverity::Error);
        UpdateStepVisuals();
        status.IsOpen(true);
    }
}
