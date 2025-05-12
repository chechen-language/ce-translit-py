import ce_translit
from ce_translit import Transliterator

class TestPublicAPI:
    def test_public_function(self):
        assert ce_translit.transliterate("халкъе") == "xalq̇e"

class TestBasicTransliteration:
    def test_transliterate_word(self):
        # Test transliteration of individual words
        assert Transliterator().transliterate("халкъе") == "xalq̇e"
        assert Transliterator().transliterate("елла") == "yella"
        assert Transliterator().transliterate("шелъелча") == "şelyelça"
        assert Transliterator().transliterate("дечиган") == "deçigaŋ"
        assert Transliterator().transliterate("чекхъели") == "çeqyeli"
        assert Transliterator().transliterate("къоьрта") == "q̇örta"
        assert Transliterator().transliterate("цхьаъ") == "cẋaə"

    def test_transliterate_text(self):
        # Test transliteration of entire text
        text = "Сан Даймохк бац хьуна абата тӏера, виначу юьртара болалац и. Сан Даймохк мотт сецна бӏешерийн кхера, сан Даймохк тарраш тӏехь лардина сий. Ца оьшуш хӏумма а тардина кхолла, ма цӏена бакъ а ду-кх заманан аз. Сан Даймохк ӏаьршашка кхевдина хӏоллам, сан Даймохк аренца къух даьлла барз."
        expected = "Saŋ Daymoxk bac ẋuna abata ṫera, vinaçu yürtara bolalac i. Saŋ Daymoxk mott secna bjeşeriyŋ qera, saŋ Daymoxk tarraş ṫeẋ lardina siy. Ca öşuş humma ə tardina qolla, ma ċena baq̇ ə du-q zamanaŋ az. Saŋ Daymoxk järşaşka qevdina hollam, saŋ Daymoxk arenca q̇ux dälla barz."
        assert ce_translit.transliterate(text) == expected

class TestSingleLetterA:
    def test_transliterate_lower_single_a(self):
        # Test transliteration of a lower single 'а' character
        text = "Мелхо а, шуна цхьанна а тхайх бала ца бархьама, дийнахь а, буса а, къа а хьоьгуш, болх бора оха"
        expected = "Melxo ə, şuna cẋanna ə txayx bala ca barẋama, diynaẋ ə, busa ə, q̇a ə ẋöguş, bolx bora oxa"
        assert ce_translit.transliterate(text) == expected
    
    def test_transliterate_upper_single_a(self):
        # Test transliteration of a upper single 'А' character
        text = "МЕЛХО А, ШУНА ЦХЬАННА А ТХАЙХ БАЛА ЦА БАРХЬАМА, ДИЙНАХЬ А, БУСА А, КЪА А ХЬОЬГУШ, БОЛХ БОРА ОХА"
        expected = "MELXO Ə, ŞUNA CẊANNA Ə TXAYX BALA CA BARẊAMA, DIYNAẊ Ə, BUSA Ə, Q̇A Ə ẊÖGUŞ, BOLX BORA OXA"
        assert ce_translit.transliterate(text) == expected

class TestMixedCases:
    def test_transliterate_mixed_case_1(self):
        # Test transliteration of mixed case "ъ" and "е" characters
        text = "къегина Къегина кЪегина КЪегина къЕгина КъЕгина кЪЕгина КЪЕгина КЪЕГИНА Къегина"
        expected = "q̇egina Q̇egina q̇egina Q̇egina q̇Egina Q̇Egina q̇Egina Q̇Egina Q̇EGINA Q̇egina"
        assert ce_translit.transliterate(text) == expected

    def test_transliterate_mixed_case_2(self):
        text = "чекхъели чекХъели чекхЪели чекХЪели чекхъЕли чекХъЕли чекхЪЕли чекХЪЕли ЧЕКХЪЕЛИ Чекхъели"
        expected = "çeqyeli çeqyeli çeqyeli çeqyeli çeqYeli çeqYeli çeqYeli çeqYeli ÇEQYELI Çeqyeli"
        assert ce_translit.transliterate(text) == expected

class TestSpecialCases:
    def test_transliterate_e(self):
        text = "еара еАра еарА еАрА ЕАра ЕАрА ЕАРА Еара"
        expected = "yeara yeAra yearA yeArA YEAra YEArA YEARA Yeara"
        assert ce_translit.transliterate(text) == expected

class TestHardSignBeforeAdoptedYeYoYuYa:
    def test_hard_sign_before_adopted_ye_yo_yu_ya(self):
        assert ce_translit.transliterate("къе") == "q̇e"
        assert ce_translit.transliterate("къё") == "q̇ö"
        assert ce_translit.transliterate("къю") == "q̇yu"
        assert ce_translit.transliterate("къя") == "q̇ya"
        assert ce_translit.transliterate("къЕ") == "q̇E"
        assert ce_translit.transliterate("къЁ") == "q̇Ö"
        assert ce_translit.transliterate("къЮ") == "q̇Yu"
        assert ce_translit.transliterate("къЯ") == "q̇Ya"

class TestCustomTransliterator:
    def test_custom_mapping(self):
        custom_mapping = {
            "а": "o",
            "б": "v"
        }
        custom_transliterator = Transliterator(mapping=custom_mapping)

        assert custom_transliterator.transliterate("аб") == "ov"
        assert custom_transliterator.transliterate("ба") == "vo"
        assert custom_transliterator.transliterate("з") == "з"

    def test_partial_mapping_override(self):
        custom_mapping = {
            **Transliterator()._mapping,
            "а": "o",
            "б": "v"
        }
        custom_transliterator = Transliterator(mapping=custom_mapping)

        assert custom_transliterator.transliterate("аб") == "ov"
        assert custom_transliterator.transliterate("ба") == "vo"
        assert custom_transliterator.transliterate("вр") == "vr"

    def test_custom_blacklist(self):
        my_black = ["хьан"]
        custom_transliterator = Transliterator(blacklist=my_black)

        # Custm blacklist should skip 'хьан'
        assert custom_transliterator.transliterate("хьан") == "ẋan"
        # Default blacklist should not apply
        assert custom_transliterator.transliterate("дин") == "diŋ"
    
    def test_custom_unsurelist(self):
        my_unsure = ["бун"]
        custom_transliterator = Transliterator(unsurelist=my_unsure)

        # Custom unsurelist should apply
        assert custom_transliterator.transliterate("бун") == "buŋ[REPLACE]"
        # Default unsurelist should not apply
        assert custom_transliterator.transliterate("шун") == "şuŋ"
