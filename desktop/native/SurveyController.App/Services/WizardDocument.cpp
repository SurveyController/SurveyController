#include "pch.h"
#include "WizardDocument.h"
#include "JsonHelpers.h"

#include <algorithm>
#include <cwctype>

namespace winrt::SurveyController::App::Services
{
    namespace
    {
        using namespace Windows::Data::Json;

        hstring StringValue(JsonObject const& object, wchar_t const* name, hstring const& fallback = {})
        {
            if (!object || !object.HasKey(name)) return fallback;
            auto value = object.GetNamedValue(name);
            return value.ValueType() == JsonValueType::String ? value.GetString() : fallback;
        }

        JsonObject Object(JsonObject const& parent, wchar_t const* name)
        {
            if (!parent || !parent.HasKey(name)) return JsonObject{};
            auto value = parent.GetNamedValue(name);
            return value.ValueType() == JsonValueType::Object ? value.GetObject() : JsonObject{};
        }

        JsonArray Array(JsonObject const& parent, wchar_t const* name)
        {
            if (!parent || !parent.HasKey(name)) return JsonArray{};
            auto value = parent.GetNamedValue(name);
            return value.ValueType() == JsonValueType::Array ? value.GetArray() : JsonArray{};
        }

        JsonObject Clone(JsonObject const& source)
        {
            if (!source) return JsonObject{};
            return JsonObject::Parse(source.Stringify());
        }

        JsonArray NumberPair(int32_t left, int32_t right)
        {
            JsonArray result;
            result.Append(JsonValue::CreateNumberValue(left));
            result.Append(JsonValue::CreateNumberValue(right));
            return result;
        }

        JsonArray StringPair(hstring const& left, hstring const& right)
        {
            JsonArray result;
            result.Append(JsonValue::CreateStringValue(left));
            result.Append(JsonValue::CreateStringValue(right));
            return result;
        }

        std::array<int32_t, 2> ReadNumberPair(JsonObject const& object, wchar_t const* name, int32_t first, int32_t second)
        {
            auto value = Array(object, name);
            if (value.Size() < 2)
            {
                return { first, second };
            }
            auto num0 = value.GetNumberAt(0);
            auto num1 = value.GetNumberAt(1);
            first = (num0 >= INT32_MIN && num0 <= INT32_MAX) ? static_cast<int32_t>(num0) : first;
            second = (num1 >= INT32_MIN && num1 <= INT32_MAX) ? static_cast<int32_t>(num1) : second;
            return { first, second };
        }

        std::array<hstring, 2> ReadStringPair(JsonObject const& object, wchar_t const* name)
        {
            auto value = Array(object, name);
            if (value.Size() < 2)
            {
                return { L"", L"" };
            }
            return { value.GetStringAt(0), value.GetStringAt(1) };
        }

    }

    WizardDocument& WizardDocument::Current()
    {
        static WizardDocument instance;
        return instance;
    }

    void WizardDocument::LoadConfigState(hstring const& json)
    {
        JsonObject state;
        hstring parseError;
        if (!TryParseJsonObject(json, state, parseError))
        {
            throw hresult_error(E_FAIL, parseError);
        }
        m_path = state.GetNamedString(L"path", L"");
        m_config = Object(state, L"config");
        m_initialized = true;
        m_dirty = false;
        ++m_revision;
    }

    void WizardDocument::SetParsedConfig(hstring const& json)
    {
        JsonObject parsed;
        hstring parseError;
        if (!TryParseJsonObject(json, parsed, parseError))
        {
            throw hresult_error(E_FAIL, parseError);
        }
        m_config = parsed;
        m_initialized = true;
        m_dirty = true;
        ++m_revision;
    }

    bool WizardDocument::HasRealSurvey() const
    {
        if (!m_config || URL().empty()) return false;
        for (auto const& value : DefinitionQuestions())
        {
            if (value.ValueType() != JsonValueType::Object) continue;
            auto question = value.GetObject();
            if (!question.GetNamedBoolean(L"is_description", false)) return true;
        }
        return false;
    }

    hstring WizardDocument::URL() const { return Survey().GetNamedString(L"url", L""); }
    hstring WizardDocument::Title() const { return Survey().GetNamedString(L"title", L""); }
    hstring WizardDocument::Provider() const { return Survey().GetNamedString(L"provider", L"wjx"); }

    uint32_t WizardDocument::QuestionCount() const
    {
        uint32_t count = 0;
        for (auto const& value : DefinitionQuestions())
        {
            if (value.ValueType() != JsonValueType::Object) continue;
            if (!value.GetObject().GetNamedBoolean(L"is_description", false)) ++count;
        }
        return count;
    }

    uint32_t WizardDocument::StrategyCount() const { return Strategies().Size(); }

    std::vector<WizardQuestion> WizardDocument::Questions() const
    {
        std::vector<WizardQuestion> result;
        for (auto const& value : DefinitionQuestions())
        {
            if (value.ValueType() != JsonValueType::Object) continue;
            auto question = value.GetObject();
            if (question.GetNamedBoolean(L"is_description", false)) continue;
            WizardQuestion item;
            item.number = static_cast<int32_t>(question.GetNamedNumber(L"num", 0));
            item.page = static_cast<int32_t>(question.GetNamedNumber(L"page", 1));
            item.pageQuestionCount = static_cast<int32_t>(question.GetNamedNumber(L"page_question_count", 0));
            item.rows = static_cast<int32_t>(question.GetNamedNumber(L"rows", 0));
            item.title = question.GetNamedString(L"title", L"");
            // Go 返回的展示 DTO 已包含规范化题型和展示字段；原生只绑定这些值。
            item.normalizedType = StringValue(question, L"normalized_type", L"unsupported");
            item.type = StringValue(question, L"type_label", L"暂不支持");
            item.required = question.GetNamedBoolean(L"required", false);
            for (auto const& option : Array(question, L"option_texts"))
            {
                if (option.ValueType() == JsonValueType::String) item.optionTexts.push_back(option.GetString());
            }
            for (auto const& row : Array(question, L"row_texts"))
            {
                if (row.ValueType() == JsonValueType::String) item.rowTexts.push_back(row.GetString());
            }
            item.options = (std::max)(static_cast<int32_t>(question.GetNamedNumber(L"options", 0)),
                static_cast<int32_t>(item.optionTexts.size()));
            item.rows = (std::max)(item.rows, static_cast<int32_t>(item.rowTexts.size()));
            item.unsupported = question.GetNamedBoolean(L"unsupported", false);
            item.unsupportedReason = question.GetNamedString(L"unsupported_reason", L"");
            item.hasJump = question.GetNamedBoolean(L"has_jump", false);
            item.hasDisplayLogic = question.GetNamedBoolean(L"has_display_condition", false);
            item.logicSummary = question.GetNamedString(L"logic_summary", L"");
            item.dimension = question.GetNamedString(L"dimension", L"");
            item.bias = question.GetNamedString(L"bias", L"custom");
            item.weights = question.GetNamedString(L"weights", L"");
            item.configured = question.GetNamedBoolean(L"configured", false);
            item.aiEnabled = question.GetNamedBoolean(L"ai_enabled", false);
            result.push_back(std::move(item));
        }
        return result;
    }

    JsonObject WizardDocument::QuestionAt(uint32_t index) const
    {
        uint32_t current = 0;
        for (auto const& value : DefinitionQuestions())
        {
            if (value.ValueType() != JsonValueType::Object) continue;
            auto question = value.GetObject();
            if (question.GetNamedBoolean(L"is_description", false)) continue;
            if (current++ == index) return question;
        }
        return JsonObject{};
    }

    JsonObject WizardDocument::StrategyAt(uint32_t index) const
    {
        auto question = QuestionAt(index);
        auto number = static_cast<int32_t>(question.GetNamedNumber(L"num", -1));
        for (auto const& value : Strategies())
        {
            if (value.ValueType() != JsonValueType::Object) continue;
            auto strategy = value.GetObject();
            if (static_cast<int32_t>(strategy.GetNamedNumber(L"question_num", -2)) == number) return strategy;
        }
        return JsonObject{};
    }

    JsonArray WizardDocument::Rules() const { return Array(Answers(), L"rules"); }
    JsonArray WizardDocument::Dimensions() const { return Array(Answers(), L"dimensions"); }

    void WizardDocument::SetSurveyURL(hstring const& value)
    {
        auto survey = Survey();
        survey.SetNamedValue(L"url", JsonValue::CreateStringValue(value));
        m_config.SetNamedValue(L"survey", survey);
        m_dirty = true;
    }

    void WizardDocument::SetExecution(int32_t target, int32_t threads, int32_t intervalMin, int32_t intervalMax,
        int32_t durationMin, int32_t durationMax, hstring const& windowStart, hstring const& windowEnd,
        bool failStop, bool pauseCaptcha)
    {
        auto execution = Execution();
        execution.SetNamedValue(L"target", JsonValue::CreateNumberValue(target));
        execution.SetNamedValue(L"threads", JsonValue::CreateNumberValue(threads));
        execution.SetNamedValue(L"submitInterval", NumberPair(intervalMin, intervalMax));
        execution.SetNamedValue(L"answerDuration", NumberPair(durationMin, durationMax));
        execution.SetNamedValue(L"answerDatetimeWindow", StringPair(windowStart, windowEnd));
        execution.SetNamedValue(L"failStop", JsonValue::CreateBooleanValue(failStop));
        execution.SetNamedValue(L"pauseOnAliyunCaptcha", JsonValue::CreateBooleanValue(pauseCaptcha));
        m_config.SetNamedValue(L"execution", execution);
        m_dirty = true;
    }

    void WizardDocument::SetNetwork(hstring const& mode, hstring const& fixedAddress, hstring const& source,
        hstring const& customApi, hstring const& areaCode, bool randomUA)
    {
        auto network = Network();
        network.SetNamedValue(L"proxyMode", JsonValue::CreateStringValue(mode));
        network.SetNamedValue(L"randomProxyEnabled", JsonValue::CreateBooleanValue(mode == L"random"));
        network.SetNamedValue(L"fixedProxyAddress", JsonValue::CreateStringValue(mode == L"fixed" ? fixedAddress : L""));
        network.SetNamedValue(L"proxySource", JsonValue::CreateStringValue(source));
        network.SetNamedValue(L"customProxyApi", JsonValue::CreateStringValue(customApi));
        network.SetNamedValue(L"proxyAreaCode", JsonValue::CreateStringValue(areaCode));
        network.SetNamedValue(L"randomUaEnabled", JsonValue::CreateBooleanValue(randomUA));
        m_config.SetNamedValue(L"network", network);
        m_dirty = true;
    }

    void WizardDocument::SetReverseFill(bool enabled, hstring const& path)
    {
        auto reverseFill = ReverseFill();
        reverseFill.SetNamedValue(L"enabled", JsonValue::CreateBooleanValue(enabled));
        reverseFill.SetNamedValue(L"sourcePath", JsonValue::CreateStringValue(path));
        m_config.SetNamedValue(L"reverseFill", reverseFill);
        m_dirty = true;
    }

    void WizardDocument::SetQuestionStrategy(uint32_t index, hstring const& dimension, hstring const& bias,
        hstring const& weights, bool aiEnabled)
    {
        JsonObject changes;
        changes.SetNamedValue(L"dimension", JsonValue::CreateStringValue(dimension));
        changes.SetNamedValue(L"psycho_bias", JsonValue::CreateStringValue(bias));
        changes.SetNamedValue(L"ai_enabled", JsonValue::CreateBooleanValue(aiEnabled));
        JsonArray options;
        std::wstring value{ weights.c_str() };
        std::replace(value.begin(), value.end(), L';', L',');
        size_t start = 0;
        while (start <= value.size())
        {
            auto end = value.find(L',', start);
            auto token = value.substr(start, end == std::wstring::npos ? std::wstring::npos : end - start);
            token.erase(std::remove_if(token.begin(), token.end(), [](wchar_t character)
            {
                return std::iswspace(character) != 0;
            }), token.end());
            try
            {
                size_t consumed = 0;
                auto number = std::stod(token, &consumed);
                if (consumed == token.size()) options.Append(JsonValue::CreateNumberValue(number));
            }
            catch (...) {}
            if (end == std::wstring::npos) break;
            start = end + 1;
        }
        if (options.Size() > 0)
        {
            JsonObject table;
            table.SetNamedValue(L"options", options);
            changes.SetNamedValue(L"custom_weights", table);
            changes.SetNamedValue(L"probabilities", Clone(table));
            changes.SetNamedValue(L"distribution_mode", JsonValue::CreateStringValue(L"custom"));
        }
        UpdateQuestionStrategy(index, changes);
    }

    void WizardDocument::UpdateQuestionStrategy(uint32_t index, JsonObject const& changes)
    {
        if (!m_config || !changes) return;
        auto question = QuestionAt(index);
        if (!question) return;
        auto num = question.GetNamedNumber(L"num", 0);
        if (num < 1.0 || num > static_cast<double>(INT32_MAX))
            return;
        auto questionNumber = static_cast<int32_t>(num);
        auto answers = Answers();
        auto strategies = Strategies();
        JsonObject strategy;
        uint32_t strategyIndex = strategies.Size();
        for (uint32_t current = 0; current < strategies.Size(); ++current)
        {
            auto value = strategies.GetAt(current);
            if (value.ValueType() != JsonValueType::Object) continue;
            auto candidate = value.GetObject();
            if (static_cast<int32_t>(candidate.GetNamedNumber(L"question_num", 0)) == questionNumber)
            {
                strategy = candidate;
                strategyIndex = current;
                break;
            }
        }
        if (!strategy)
        {
            strategy = JsonObject{};
            strategy.SetNamedValue(L"question_num", JsonValue::CreateNumberValue(questionNumber));
        }
        for (auto const& pair : changes)
        {
            auto value = pair.Value();
            if (value.ValueType() == JsonValueType::Null) strategy.Remove(pair.Key());
            else strategy.SetNamedValue(pair.Key(), value);
        }
        if (strategyIndex == strategies.Size()) strategies.Append(strategy);
        else strategies.SetAt(strategyIndex, strategy);
        answers.SetNamedValue(L"questions", strategies);
        m_config.SetNamedValue(L"answers", answers);
        m_dirty = true;
    }

    void WizardDocument::SetRule(int32_t index, JsonObject const& rule)
    {
        auto rules = Rules();
        if (index >= 0 && static_cast<uint32_t>(index) < rules.Size())
        {
            rules.SetAt(static_cast<uint32_t>(index), rule);
        }
        else
        {
            rules.Append(rule);
        }
        auto answers = Answers();
        answers.SetNamedValue(L"rules", rules);
        m_config.SetNamedValue(L"answers", answers);
        m_dirty = true;
    }

    void WizardDocument::DeleteRule(uint32_t index)
    {
        auto rules = Rules();
        if (index >= rules.Size()) return;
        rules.RemoveAt(index);
        auto answers = Answers();
        answers.SetNamedValue(L"rules", rules);
        m_config.SetNamedValue(L"answers", answers);
        m_dirty = true;
    }

    bool WizardDocument::MoveRule(uint32_t from, uint32_t to)
    {
        auto rules = Rules();
        if (from >= rules.Size() || to >= rules.Size() || from == to) return false;
        auto value = rules.GetAt(from);
        rules.RemoveAt(from);
        rules.InsertAt(to, value);
        auto answers = Answers();
        answers.SetNamedValue(L"rules", rules);
        m_config.SetNamedValue(L"answers", answers);
        m_dirty = true;
        return true;
    }

    bool WizardDocument::MoveRuleUp(uint32_t index)
    {
        return index > 0 && MoveRule(index, index - 1);
    }

    bool WizardDocument::MoveRuleDown(uint32_t index)
    {
        auto rules = Rules();
        return index + 1 < rules.Size() && MoveRule(index, index + 1);
    }

    hstring WizardDocument::ValidateRule(JsonObject const& rule) const
    {
        UNREFERENCED_PARAMETER(rule);
        return {};
    }

    void WizardDocument::SetDimensions(JsonArray const& dimensions)
    {
        auto answers = Answers();
        answers.SetNamedValue(L"dimensions", dimensions);
        m_config.SetNamedValue(L"answers", answers);
        m_dirty = true;
    }

    void WizardDocument::SetPsychometrics(bool enabled, double targetAlpha)
    {
        auto psychometrics = Psychometrics();
        psychometrics.SetNamedValue(L"enabled", JsonValue::CreateBooleanValue(enabled));
        psychometrics.SetNamedValue(L"targetAlpha", JsonValue::CreateNumberValue(targetAlpha));
        m_config.SetNamedValue(L"psychometrics", psychometrics);
        m_dirty = true;
    }

    int32_t WizardDocument::Target() const { return static_cast<int32_t>(Execution().GetNamedNumber(L"target", 1)); }
    int32_t WizardDocument::Threads() const { return static_cast<int32_t>(Execution().GetNamedNumber(L"threads", 1)); }
    std::array<int32_t, 2> WizardDocument::SubmitInterval() const { return ReadNumberPair(Execution(), L"submitInterval", 0, 0); }
    std::array<int32_t, 2> WizardDocument::AnswerDuration() const { return ReadNumberPair(Execution(), L"answerDuration", 60, 120); }
    std::array<hstring, 2> WizardDocument::AnswerWindow() const { return ReadStringPair(Execution(), L"answerDatetimeWindow"); }
    bool WizardDocument::FailStop() const { return Execution().GetNamedBoolean(L"failStop", true); }
    bool WizardDocument::PauseCaptcha() const { return Execution().GetNamedBoolean(L"pauseOnAliyunCaptcha", true); }
    hstring WizardDocument::ProxyMode() const { return Network().GetNamedString(L"proxyMode", Network().GetNamedBoolean(L"randomProxyEnabled", false) ? L"random" : L"direct"); }
    hstring WizardDocument::FixedProxyAddress() const { return Network().GetNamedString(L"fixedProxyAddress", L""); }
    hstring WizardDocument::ProxySource() const { return Network().GetNamedString(L"proxySource", L"default"); }
    hstring WizardDocument::CustomProxyAPI() const { return Network().GetNamedString(L"customProxyApi", L""); }
    hstring WizardDocument::ProxyAreaCode() const { return Network().GetNamedString(L"proxyAreaCode", L""); }
    bool WizardDocument::RandomUA() const { return Network().GetNamedBoolean(L"randomUaEnabled", false); }
    bool WizardDocument::ReverseFillEnabled() const { return ReverseFill().GetNamedBoolean(L"enabled", false); }
    hstring WizardDocument::ReverseFillPath() const { return ReverseFill().GetNamedString(L"sourcePath", L""); }
    bool WizardDocument::PsychometricsEnabled() const { return Psychometrics().GetNamedBoolean(L"enabled", false); }
    double WizardDocument::TargetAlpha() const { return Psychometrics().GetNamedNumber(L"targetAlpha", 0.85); }

    hstring WizardDocument::CheckRequest(JsonObject const& settings) const
    {
        JsonObject request;
        request.SetNamedValue(L"config", m_config);
        request.SetNamedValue(L"aiProfile", settings.GetNamedObject(L"aiProfile", JsonObject{}));
        return request.Stringify();
    }

    hstring WizardDocument::SaveRequest() const
    {
        JsonObject request;
        request.SetNamedValue(L"path", JsonValue::CreateStringValue(m_path));
        request.SetNamedValue(L"config", m_config);
        return request.Stringify();
    }

    hstring WizardDocument::RunRequest() const
    {
        JsonObject request;
        request.SetNamedValue(L"config", m_config);
        return request.Stringify();
    }

    hstring WizardDocument::ConfigState() const
    {
        JsonObject state;
        state.SetNamedValue(L"path", JsonValue::CreateStringValue(m_path));
        state.SetNamedValue(L"config", m_config ? m_config : JsonObject{});
        return state.Stringify();
    }

    JsonObject WizardDocument::Survey() const { return m_config ? Object(m_config, L"survey") : JsonObject{}; }
    JsonObject WizardDocument::Execution() const { return m_config ? Object(m_config, L"execution") : JsonObject{}; }
    JsonObject WizardDocument::Network() const { return m_config ? Object(m_config, L"network") : JsonObject{}; }
    JsonObject WizardDocument::ReverseFill() const { return m_config ? Object(m_config, L"reverseFill") : JsonObject{}; }
    JsonObject WizardDocument::Answers() const { return m_config ? Object(m_config, L"answers") : JsonObject{}; }
    JsonObject WizardDocument::Psychometrics() const { return m_config ? Object(m_config, L"psychometrics") : JsonObject{}; }
    JsonArray WizardDocument::DefinitionQuestions() const { return Array(Object(Survey(), L"definition"), L"questions"); }
    JsonArray WizardDocument::Strategies() const { return m_config ? Array(Object(m_config, L"answers"), L"questions") : JsonArray{}; }
}
