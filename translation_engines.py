import os
from pathlib import Path
from typing import Optional

import argostranslate.package
import argostranslate.translate


class TranslationUnavailable(Exception):
    pass


AFRINLLB_MODEL_NAME = os.getenv(
    "AFRINLLB_MODEL",
    "AfriNLP/AfriNLLB-12enc-8dec-iterative-548m-ft",
)
AFRINLLB_CT2_DIR = os.getenv("AFRINLLB_CT2_DIR", "ct2")
AFRINLLB_DEVICE = os.getenv("AFRINLLB_DEVICE", "cpu")
AFRINLLB_COMPUTE_TYPE = os.getenv("AFRINLLB_COMPUTE_TYPE", "default")
AFRINLLB_BATCH_SIZE = int(os.getenv("AFRINLLB_BATCH_SIZE", "8"))


AFRINLLB_LANG_CODES = {
    "af": "afr_Latn",
    "am": "amh_Ethi",
    "ar": "arb_Arab",
    "arz": "arz_Arab",
    "en": "eng_Latn",
    "es": "spa_Latn",
    "fr": "fra_Latn",
    "ha": "hau_Latn",
    "ln": "lin_Latn",
    "pt": "por_Latn",
    "so": "som_Latn",
    "sw": "swh_Latn",
    "wo": "wol_Latn",
    "yo": "yor_Latn",
    "zu": "zul_Latn",
}

AFRINLLB_AFRICAN_LANGS = {
    "af",
    "am",
    "arz",
    "ha",
    "ln",
    "so",
    "sw",
    "wo",
    "yo",
    "zu",
}

AFRINLLB_ENGLISH_PAIRS = {
    "af",
    "am",
    "ar",
    "arz",
    "es",
    "fr",
    "ha",
    "ln",
    "pt",
    "so",
    "sw",
    "wo",
    "yo",
    "zu",
}
AFRINLLB_FRENCH_PAIRS = {"ln", "wo"}


def normalize_lang(code: Optional[str], default: str = "en") -> str:
    if not code or code == "auto":
        return default
    return code.split("-")[0].lower()


def format_segments(segments: list, translations: list[str]) -> list:
    return [
        {
            "start": seg["start"],
            "end": seg["end"],
            "text": translation,
            "original": seg["text"],
        }
        for seg, translation in zip(segments, translations)
    ]


class ArgosTranslator:
    def __init__(self):
        print("🔄 Updating Argos Translate language packs...")
        argostranslate.package.update_package_index()
        self.available_packages = argostranslate.package.get_available_packages()
        print(f"   Found {len(self.available_packages)} language packs available")

    def installed_languages(self):
        return argostranslate.translate.get_installed_languages()

    def ensure_pair(self, source_code: str, target_code: str) -> bool:
        installed = self.installed_languages()
        installed_codes = [lang.code for lang in installed]
        if source_code in installed_codes and target_code in installed_codes:
            source_lang = next((l for l in installed if l.code == source_code), None)
            target_lang = next((l for l in installed if l.code == target_code), None)
            if source_lang and target_lang and source_lang.get_translation(target_lang):
                return True

        for pkg in self.available_packages:
            if pkg.from_code == source_code and pkg.to_code == target_code:
                print(f"📦 Installing Argos language pack: {source_code} → {target_code}...")
                argostranslate.package.install_from_path(pkg.download())
                print(f"✅ Installed Argos {source_code} → {target_code}")
                return True
        return False

    def translate_segments(self, segments: list, source_code: str, target_code: str) -> list:
        if source_code == target_code:
            return format_segments(segments, [s["text"] for s in segments])

        pair_ok = self.ensure_pair(source_code, target_code)
        if not pair_ok and source_code != "en" and target_code != "en":
            p1 = self.ensure_pair(source_code, "en")
            p2 = self.ensure_pair("en", target_code)
            if p1 and p2:
                print(f"🔄 Argos pivot: {source_code} → en → {target_code}")
                english = self._translate_texts([s["text"] for s in segments], source_code, "en")
                translated = self._translate_texts(english, "en", target_code)
                return format_segments(segments, translated)

        if not pair_ok:
            raise TranslationUnavailable(
                f"Translation unavailable: {source_code} → {target_code} is not supported by Argos Translate."
            )

        translated = self._translate_texts([s["text"] for s in segments], source_code, target_code)
        return format_segments(segments, translated)

    def _translate_texts(self, texts: list[str], source_code: str, target_code: str) -> list[str]:
        print(f"🌍 Argos translating {len(texts)} segments: {source_code} → {target_code}")
        translated = []
        for i, text in enumerate(texts):
            translated.append(argostranslate.translate.translate(text, source_code, target_code))
            if (i + 1) % 10 == 0:
                print(f"   {i + 1}/{len(texts)}...")
        return translated


class AfriNLLBTranslator:
    def __init__(self):
        self.translator = None
        self.sentencepiece = None

    def supports_pair(self, source_code: str, target_code: str) -> bool:
        src = normalize_lang(source_code)
        tgt = normalize_lang(target_code)
        if src == tgt:
            return False

        if src == "en" and tgt in AFRINLLB_ENGLISH_PAIRS:
            return tgt in AFRINLLB_AFRICAN_LANGS
        if tgt == "en" and src in AFRINLLB_ENGLISH_PAIRS:
            return src in AFRINLLB_AFRICAN_LANGS
        if src == "fr" and tgt in AFRINLLB_FRENCH_PAIRS:
            return True
        if tgt == "fr" and src in AFRINLLB_FRENCH_PAIRS:
            return True
        return False

    def handles_language(self, code: str) -> bool:
        return normalize_lang(code) in AFRINLLB_AFRICAN_LANGS

    def translate_segments(self, segments: list, source_code: str, target_code: str) -> list:
        src = AFRINLLB_LANG_CODES.get(normalize_lang(source_code))
        tgt = AFRINLLB_LANG_CODES.get(normalize_lang(target_code))
        if not src or not tgt or not self.supports_pair(source_code, target_code):
            raise TranslationUnavailable(
                f"Translation unavailable: {source_code} → {target_code} is not supported by AfriNLLB."
            )

        self._load()
        print(f"🌍 AfriNLLB translating {len(segments)} segments: {src} → {tgt}")
        translations = []
        texts = [s["text"] for s in segments]
        for start in range(0, len(texts), AFRINLLB_BATCH_SIZE):
            batch = texts[start:start + AFRINLLB_BATCH_SIZE]
            translations.extend(self._translate_batch(batch, src, tgt))
            print(f"   {min(start + AFRINLLB_BATCH_SIZE, len(texts))}/{len(texts)}...")
        return format_segments(segments, translations)

    def _load(self):
        if self.translator and self.sentencepiece:
            return

        try:
            import ctranslate2
            import sentencepiece as spm
            from huggingface_hub import hf_hub_download, snapshot_download
        except ImportError as e:
            raise TranslationUnavailable(
                "AfriNLLB dependencies are not installed. Run: pip install -r requirements.txt"
            ) from e

        cache_dir = Path(os.getenv("AFRINLLB_CACHE_DIR", Path(__file__).resolve().parent / "models"))
        model_dir = snapshot_download(
            repo_id=AFRINLLB_MODEL_NAME,
            allow_patterns=[f"{AFRINLLB_CT2_DIR}/*"],
            cache_dir=str(cache_dir),
        )
        ct2_model_path = Path(model_dir) / AFRINLLB_CT2_DIR

        spm_path = ct2_model_path / "sentencepiece.bpe.model"
        if not spm_path.exists():
            hf_hub_download(
                repo_id="facebook/nllb-200-distilled-600M",
                filename="sentencepiece.bpe.model",
                local_dir=str(ct2_model_path),
            )

        self.sentencepiece = spm.SentencePieceProcessor()
        self.sentencepiece.load(str(spm_path))
        self.translator = ctranslate2.Translator(
            str(ct2_model_path),
            device=AFRINLLB_DEVICE,
            compute_type=AFRINLLB_COMPUTE_TYPE,
        )

    def _translate_batch(self, texts: list[str], source_code: str, target_code: str) -> list[str]:
        encoded = self.sentencepiece.encode_as_pieces(texts)
        encoded = [[source_code] + pieces + ["</s>"] for pieces in encoded]
        results = self.translator.translate_batch(
            encoded,
            target_prefix=[[target_code]] * len(encoded),
            beam_size=5,
            max_decoding_length=256,
        )

        translations = []
        for result in results:
            tokens = result.hypotheses[0]
            if tokens and tokens[0] == target_code:
                tokens = tokens[1:]
            translations.append(self.sentencepiece.decode_pieces(tokens))
        return translations


class TranslationService:
    def __init__(self):
        self.argos = ArgosTranslator()
        self.afrinllb = AfriNLLBTranslator()

    def installed_argos_languages(self):
        return self.argos.installed_languages()

    def translate_segments(self, segments: list, source_lang: str, target_lang: str) -> list:
        source_code = normalize_lang(source_lang)
        target_code = normalize_lang(target_lang)

        if source_code == target_code:
            return format_segments(segments, [s["text"] for s in segments])

        if self.afrinllb.supports_pair(source_code, target_code):
            return self.afrinllb.translate_segments(segments, source_code, target_code)

        if self.afrinllb.handles_language(target_code) and self.afrinllb.supports_pair("en", target_code):
            print(
                f"🔄 Pivot translation: {source_code} → en with Argos, "
                f"then en → {target_code} with AfriNLLB"
            )
            english_segments = self.argos.translate_segments(segments, source_code, "en")
            return self.afrinllb.translate_segments(english_segments, "en", target_code)

        if self.afrinllb.handles_language(source_code) and self.afrinllb.supports_pair(source_code, "en"):
            print(
                f"🔄 Pivot translation: {source_code} → en with AfriNLLB, "
                f"then en → {target_code} with Argos"
            )
            english_segments = self.afrinllb.translate_segments(segments, source_code, "en")
            return self.argos.translate_segments(english_segments, "en", target_code)

        if self.afrinllb.handles_language(source_code) or self.afrinllb.handles_language(target_code):
            raise TranslationUnavailable(
                f"Translation unavailable: {source_code} → {target_code} is not supported directly, "
                "and no supported English pivot path is available."
            )

        return self.argos.translate_segments(segments, source_code, target_code)
