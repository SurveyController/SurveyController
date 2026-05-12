from __future__ import annotations

from software.network.proxy.areas import service


def _reset_area_caches() -> None:
    service._AREA_CODES_CACHE = None
    service._SUPPORTED_CODES_CACHE = None
    service._BENEFIT_SUPPORTED_AREAS_CACHE = None
    service._BENEFIT_CITY_CODE_INDEX_CACHE = None


class ProxyAreaServiceTests:
    @staticmethod
    def _fake_area_codes_for_benefit_online(supported_only: bool = False):
        assert supported_only is False
        return [
            {
                "code": "440000",
                "name": "广东省",
                "cities": [
                    {"code": "440100", "name": "广州市"},
                    {"code": "440300", "name": "深圳市"},
                    {"code": "441900", "name": "东莞市"},
                ],
            },
            {
                "code": "110000",
                "name": "北京市",
                "cities": [{"code": "110100", "name": "市辖区"}],
            },
        ]

    @staticmethod
    def _fake_area_codes_for_benefit_fallback(supported_only: bool = False):
        assert supported_only is False
        return [
            {
                "code": "440000",
                "name": "广东省",
                "cities": [{"code": "440100", "name": "广州市"}],
            },
            {
                "code": "110000",
                "name": "北京市",
                "cities": [{"code": "110100", "name": "市辖区"}],
            },
        ]

    def test_load_supported_area_codes_ignores_comments_and_tracks_all(self, patch_attrs) -> None:
        _reset_area_caches()
        patch_attrs(
            (
                service,
                "_read_asset_text",
                lambda name: "北京 110100\n# 注释\nbad-line\n全部 all\n上海 310100\n"
                if name == "area.txt"
                else "",
            )
        )

        codes, has_all = service.load_supported_area_codes()

        assert codes == {"110100", "310100"}
        assert has_all is True

    def test_load_area_codes_filters_supported_cities(self, patch_attrs) -> None:
        _reset_area_caches()
        payload = {
            "provinces": [
                {
                    "code": "110000",
                    "name": "北京市",
                    "cities": [
                        {"code": "110100", "name": "市辖区"},
                        {"code": "110200", "name": "不支持"},
                    ],
                },
                {
                    "code": "310000",
                    "name": "上海市",
                    "cities": [{"code": "310100", "name": "市辖区"}],
                },
            ]
        }
        patch_attrs(
            (
                service,
                "_read_asset_text",
                lambda name: '{"provinces":[{"code":"110000","name":"北京市","cities":[{"code":"110100","name":"市辖区"},{"code":"110200","name":"不支持"}]},{"code":"310000","name":"上海市","cities":[{"code":"310100","name":"市辖区"}]}]}'
                if name == "area_codes_2022.json"
                else "北京 110100\n",
            )
        )

        all_areas = service.load_area_codes(supported_only=False)
        supported = service.load_area_codes(supported_only=True)

        assert all_areas == payload["provinces"]
        assert supported == [
            {
                "code": "110000",
                "name": "北京市",
                "cities": [{"code": "110100", "name": "市辖区"}],
            }
        ]

    def test_parse_benefit_area_text_normalizes_province_and_city_names(self) -> None:
        content = """
        省份：广东省
        城市：广州市 运营商：电信
        城市：深圳市
        省份：内蒙古自治区
        城市：呼和浩特市
        """

        parsed = service._parse_benefit_area_text(content)

        assert parsed == {"广东": {"广州", "深圳"}, "内蒙古": {"呼和浩特"}}

    def test_benefit_online_data_matches_local_tree(self, patch_attrs) -> None:
        _reset_area_caches()
        patch_attrs(
            (
                service,
                "load_area_codes",
                self._fake_area_codes_for_benefit_online,
            ),
            (
                service,
                "_download_benefit_area_text",
                lambda: "省份：广东省\n城市：深圳市 运营商：联通\n省份：北京市\n城市：北京\n",
            ),
        )

        areas, index = service._build_benefit_supported_data_from_online()

        assert areas == [
            {"code": "440000", "name": "广东省", "cities": [{"code": "440300", "name": "深圳市"}]},
            {"code": "110000", "name": "北京市", "cities": [{"code": "110100", "name": "市辖区"}]},
        ]
        assert index == {"440300": "深圳", "110100": "北京"}

    def test_benefit_cache_falls_back_to_local_codes_after_online_failure(self, patch_attrs) -> None:
        _reset_area_caches()
        patch_attrs(
            (
                service,
                "load_supported_area_codes",
                lambda: ({"440100", "110100"}, False),
            ),
            (
                service,
                "load_area_codes",
                self._fake_area_codes_for_benefit_fallback,
            ),
            (
                service,
                "_build_benefit_supported_data_from_online",
                lambda: (_ for _ in ()).throw(RuntimeError("network down")),
            ),
        )

        assert service.resolve_proxy_area_for_source("default", "440100") == "440100"
        assert service.resolve_proxy_area_for_source("benefit", "440100") == "广州"
        assert service.resolve_proxy_area_for_source("benefit", "bad") == ""
        assert service.build_benefit_city_code_index() == {"440100": "广州", "110100": "北京"}
