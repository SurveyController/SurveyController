from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from software.core.task import ExecutionConfig, ExecutionState
from surveycore.core.engine.stop_signal import StopSignalLike
from surveycore.core.user_agent import UserAgentProfile
from surveycore.providers.contracts import SurveyDefinition


class ProviderErrorCategory(StrEnum):
    CANCELLED = "cancelled"
    CONFIGURATION = "configuration"
    NETWORK = "network"
    UNAVAILABLE = "unavailable"
    SUBMISSION_REJECTED = "submission_rejected"
    VERIFICATION_REQUIRED = "verification_required"
    UNKNOWN = "unknown"


class ProviderSubmissionRejectedError(RuntimeError):
    """A provider explicitly rejected a submitted response."""


@dataclass(frozen=True)
class ProviderFailure:
    provider: str
    category: ProviderErrorCategory
    message: str
    exception: Exception


@dataclass(frozen=True)
class ProviderParseResult:
    provider: str
    definition: SurveyDefinition | None = None
    failure: ProviderFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.definition is not None and self.failure is None


@dataclass(frozen=True)
class ProviderSubmissionResult:
    provider: str
    submitted: bool
    failure: ProviderFailure | None = None

    @property
    def succeeded(self) -> bool:
        return self.submitted and self.failure is None


@dataclass(frozen=True)
class ProviderProxyLease:
    address: str | None
    provider: str


SubmitProxyLeaseFactory = Callable[[], Awaitable[ProviderProxyLease]]


class ProviderAdapter(Protocol):
    provider: str

    async def parse_survey_async(self, url: str) -> ProviderParseResult: ...

    async def fill_survey_http_async(
        self,
        config: ExecutionConfig,
        state: ExecutionState,
        *,
        stop_signal: StopSignalLike | None = None,
        thread_name: str = "",
        psycho_plan: object | None = None,
        proxy_address: str | None = None,
        user_agent: str | None = None,
        user_agent_profile: UserAgentProfile | None = None,
        submit_proxy_lease_factory: SubmitProxyLeaseFactory | None = None,
    ) -> ProviderSubmissionResult: ...


__all__ = [
    "ProviderAdapter",
    "ProviderErrorCategory",
    "ProviderFailure",
    "ProviderParseResult",
    "ProviderProxyLease",
    "ProviderSubmissionRejectedError",
    "ProviderSubmissionResult",
    "SubmitProxyLeaseFactory",
]
