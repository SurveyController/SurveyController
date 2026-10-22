from __future__ import annotations

from hypothesis import given, strategies as st

from software.network.proxy.pool import coerce_proxy_lease


@given(
    host=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
        min_size=1,
        max_size=32,
    ),
    port=st.integers(min_value=1, max_value=65535),
)
def test_proxy_lease_normalization_is_stable(host: str, port: int) -> None:
    lease = coerce_proxy_lease(f"{host}:{port}", source="custom")

    assert lease is not None
    assert lease.address == f"http://{host}:{port}"
    assert coerce_proxy_lease(lease) == lease
