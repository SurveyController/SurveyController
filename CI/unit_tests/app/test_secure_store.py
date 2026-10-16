import software.system.secure_store as secure_store


class SecureStoreTests:
    def test_invalid_key(self) -> None:
        assert secure_store.read_secret("").status == "invalid_key"
