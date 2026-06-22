import { Call as $Call, CancellablePromise as $CancellablePromise } from "@wailsio/runtime";
import * as reversefill$0 from "../../../../../surveycontroller/surveycore/reversefill/models.js";
import * as $models from "./models.js";

export function BuildDefaultConfig(request: $models.ParseSurveyRequest): $CancellablePromise<$models.SurveyCoreState> {
    return $Call.ByID(1281628077, request);
}

export function CancelRun(): $CancellablePromise<$models.RunTaskState> {
    return $Call.ByID(56584525);
}

export function GetAppSettings(): $CancellablePromise<$models.AppSettings> {
    return $Call.ByID(120288048);
}

export function GetProxyStatus(): $CancellablePromise<$models.ProxyStatus> {
    return $Call.ByID(3425455756);
}

export function GetRunTaskState(): $CancellablePromise<$models.RunTaskState> {
    return $Call.ByID(2123585291);
}

export function GetShellState(): $CancellablePromise<$models.ShellState> {
    return $Call.ByID(4132789757);
}

export function LoadConfig(request: $models.LoadConfigRequest): $CancellablePromise<$models.ConfigFileState> {
    return $Call.ByID(1600851788, request);
}

export function ParseSurvey(request: $models.ParseSurveyRequest): $CancellablePromise<$models.SurveyCoreState> {
    return $Call.ByID(2302332847, request);
}

export function PreviewReverseFill(request: $models.ReverseFillPreviewRequest): $CancellablePromise<reversefill$0.Preview> {
    return $Call.ByID(2827367849, request);
}

export function RunSurvey(request: $models.RunSurveyRequest): $CancellablePromise<$models.SurveyCoreState> {
    return $Call.ByID(816852985, request);
}

export function SaveAppSettings(request: $models.SaveSettingsRequest): $CancellablePromise<$models.AppSettings> {
    return $Call.ByID(236977175, request);
}

export function SaveConfig(request: $models.SaveConfigRequest): $CancellablePromise<$models.ConfigFileState> {
    return $Call.ByID(2775748437, request);
}

export function StartRun(request: $models.RunSurveyRequest): $CancellablePromise<$models.RunTaskState> {
    return $Call.ByID(1211922163, request);
}
