#include "pch.h"
#include "IPUsageRow.h"

#if __has_include("IPUsageRow.g.cpp")
#include "IPUsageRow.g.cpp"
#endif

namespace winrt::SurveyController::App::implementation
{
    IPUsageRow::IPUsageRow(hstring const& label, double total, double maximum)
        : m_label(label)
        , m_total(std::isfinite(total) ? total : 0.0)
        , m_maximum((std::isfinite(maximum) && maximum > 0) ? maximum : 1.0)
    {
    }
}
