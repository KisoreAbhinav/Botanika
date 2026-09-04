"""Shared settings for the Botanika local application and Phase 9 extras."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import os
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[4]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "models" / "yolo11n-coco.json"
DEFAULT_QUALITY_CONFIG = PROJECT_ROOT / "config" / "vision" / "phase3-quality-baseline.json"
DEFAULT_SPECIES_CATALOG = PROJECT_ROOT / "config" / "catalog" / "india-starter-species.json"
DEFAULT_CLASSIFIER_MODEL = PROJECT_ROOT / "models" / "plant_classifier" / "india-starter-feature-v1.json"
DEFAULT_LLM_MODEL = PROJECT_ROOT / "models" / "llm" / "botanika.gguf"
DEFAULT_STT_MODELS = PROJECT_ROOT / "models" / "stt"
DEFAULT_TTS_MODELS = PROJECT_ROOT / "models" / "tts"
DEFAULT_WEED_MANIFEST = PROJECT_ROOT / "config" / "weed" / "phase9-beta.json"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "database" / "botanika.sqlite"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Validated configuration for the modular monolith.

    SOLO remains the default and binds to loopback.  Phase 7 network mode uses
    a wildcard listener together with the AP-only firewall unit; this keeps
    both the kiosk's loopback path and the controlled private Wi-Fi path alive.
    Paths are resolved eagerly so a misconfigured layout fails at startup
    instead of during a request.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    loopback_only: bool = True
    network_enabled: bool = False
    access_point_interface: str = "wlan0"
    access_point_address: str = "192.168.50.1"
    access_point_prefix_length: int = 24
    access_point_ssid: str = "Botanika"
    access_point_connection_name: str = "botanika-ap"
    local_hostname: str = "botanika.home.arpa"
    wifi_country_code: str = "IN"
    network_stack: str = "auto"

    # Optional internet transport.  This is deliberately independent from
    # the private access point: the supported no-account Quick Tunnel setup
    # binds cloudflared to this process's loopback API and can therefore run
    # with ``BOTANIKA_NETWORK_ENABLED=false``.
    tunnel_enabled: bool = False
    cloudflared_path: str = "/usr/local/bin/cloudflared"
    cloudflared_name: str | None = None
    tunnel_startup_timeout_seconds: float = 15.0

    # Phase 8 mode handoff.  ``None`` means no physical GPIO is configured;
    # the HTTP/keyboard software fallback remains available for development.
    mode_button_pin: int | None = None
    solo_led_pin: int | None = None
    networked_led_pin: int | None = None
    paired_led_pin: int | None = None
    gpio_debounce_ms: int = 250
    pairing_ttl_seconds: float = 300.0
    pairing_code_length: int = 8
    controller_health_timeout_seconds: float = 45.0

    # Vision pipeline
    manifest_path: Path = DEFAULT_MANIFEST
    quality_config_path: Path = DEFAULT_QUALITY_CONFIG
    eligible_labels: frozenset[str] = field(default_factory=lambda: frozenset({"potted plant"}))
    detector_confidence: float = 0.25
    detector_nms_iou: float = 0.45
    stable_checks: int = 4
    appearance_similarity: float = 0.70
    cooldown_frames: int = 30
    crop_padding_ratio: float = 0.08

    # Phase 6 catalog/model release. The artifact is loaded once by the scan
    # owner; a missing or invalid artifact is an honest unavailable state.
    species_catalog_path: Path = DEFAULT_SPECIES_CATALOG
    classifier_model_path: Path = DEFAULT_CLASSIFIER_MODEL
    acceptance_threshold: float = 0.62

    # Phase 9A: optional local generation and one-owner voice pipeline.  These
    # paths are opt-in artifacts; the application never downloads them.
    llm_model_path: Path = DEFAULT_LLM_MODEL
    llm_backend: str = "auto"
    # Explicit executable path keeps the service independent of a shell PATH;
    # the binary is installed separately and is never downloaded by Botanika.
    llama_cli_path: str = "/usr/local/bin/llama-cli"
    llm_context_tokens: int = 2048
    llm_threads: int = 4
    llm_batch_size: int = 128
    llm_temperature: float = 0.1
    llm_max_tokens: int = 256
    llm_timeout_seconds: float = 20.0
    stt_provider: str = "vosk"
    stt_models_path: Path = DEFAULT_STT_MODELS
    stt_model_name: str | None = None
    tts_provider: str = "piper"
    tts_models_path: Path = DEFAULT_TTS_MODELS
    tts_model_name: str | None = None
    voice_sample_rate: int = 16000
    voice_chunk_ms: int = 80
    voice_silence_rms: int = 500
    voice_start_timeout_seconds: float = 5.0
    voice_short_silence_seconds: float = 1.0
    voice_long_silence_seconds: float = 5.0
    voice_max_turn_seconds: float = 30.0
    voice_max_audio_bytes: int = 8 * 1024 * 1024
    voice_tts_timeout_seconds: float = 30.0

    # Phase 9C: independently validated weed-beta model contract.  The
    # tracked manifest may intentionally point at an absent artifact.
    weed_manifest_path: Path = DEFAULT_WEED_MANIFEST
    weed_confidence: float = 0.35
    weed_nms_iou: float = 0.45
    weed_max_upload_bytes: int = 12 * 1024 * 1024
    weed_position_max_accuracy_m: float = 100.0

    # Preview stream contract shared with the kiosk overlay.
    preview_width: int = 500
    preview_height: int = 330
    preview_jpeg_quality: int = 72
    max_fallback_upload_bytes: int = 12 * 1024 * 1024
    max_remote_crop_upload_bytes: int = 12 * 1024 * 1024

    # Managed runtime data
    database_path: Path = DEFAULT_SQLITE_PATH
    temp_crops_dir: Path = PROJECT_ROOT / "data" / "media" / "temp" / "phase6-crops"
    discoveries_dir: Path | None = None
    backup_dir: Path = PROJECT_ROOT / "data" / "backups"
    library_quota_bytes: int = 2 * 1024 * 1024 * 1024
    library_quota_observations: int = 10000

    max_consecutive_drops: int = 30
    event_backlog: int = 50
    request_log_limit: int = 200
    save_deduplication_seconds: float = 5.0
    # Compatibility fields for Phase 5 tests/config callers. New runtime code
    # uses discoveries_dir and save_deduplication_seconds.
    demo_discoveries_dir: Path = PROJECT_ROOT / "data" / "media" / "discoveries" / "demo"
    demo_save_deduplication_seconds: float = 5.0
    legacy_demo_mode: bool = field(default=False, init=False)

    @property
    def pairing_url(self) -> str:
        """URL a phone should open after joining the private access point."""

        return f"http://{self.access_point_address}:{self.port}/"

    def __post_init__(self) -> None:
        legacy_demo_mode = self.discoveries_dir is None and (
            self.demo_discoveries_dir
            != PROJECT_ROOT / "data" / "media" / "discoveries" / "demo"
        )
        object.__setattr__(self, "legacy_demo_mode", legacy_demo_mode)
        if self.discoveries_dir is None:
            # Phase 5 callers passed only demo_discoveries_dir. Honour that
            # explicit temporary location while the new default stays real.
            resolved_discoveries = (
                self.demo_discoveries_dir
                if self.demo_discoveries_dir != PROJECT_ROOT / "data" / "media" / "discoveries" / "demo"
                else PROJECT_ROOT / "data" / "media" / "discoveries" / "real"
            )
            object.__setattr__(self, "discoveries_dir", resolved_discoveries)
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.network_enabled:
            if self.loopback_only and self.host != "127.0.0.1":
                raise ValueError(
                    "safe AP fallback mode must bind to loopback (127.0.0.1)"
                )
            if not self.loopback_only and self.host != "0.0.0.0":
                raise ValueError(
                    "active network mode must use the firewall-restricted 0.0.0.0 "
                    "listener so loopback remains available"
                )
            if self.port == 0:
                raise ValueError("network mode requires a fixed API port")
        elif self.host != "127.0.0.1":
            raise ValueError(
                "a non-loopback listener requires Phase 7 network_enabled=True"
            )
        if self.tunnel_enabled and self.port == 0:
            raise ValueError("tunnel mode requires a fixed API port")
        if (
            not isinstance(self.cloudflared_path, str)
            or not self.cloudflared_path.strip()
            or any(character in self.cloudflared_path for character in "\x00\r\n")
        ):
            raise ValueError("cloudflared_path must be a non-empty executable name or path")
        if self.cloudflared_name is not None and (
            not isinstance(self.cloudflared_name, str)
            or not self.cloudflared_name.strip()
            or any(character in self.cloudflared_name for character in "\x00\r\n")
        ):
            raise ValueError("cloudflared_name must be a non-empty executable name when set")
        if (
            isinstance(self.tunnel_startup_timeout_seconds, bool)
            or not isinstance(self.tunnel_startup_timeout_seconds, (int, float))
            or not math.isfinite(float(self.tunnel_startup_timeout_seconds))
            or self.tunnel_startup_timeout_seconds <= 0
        ):
            raise ValueError("tunnel_startup_timeout_seconds must be positive")
        # Validate the AP values in one place shared with the operator tool.
        from botanika.network.config import AccessPointConfig

        AccessPointConfig(
            interface=self.access_point_interface,
            address=self.access_point_address,
            prefix_length=self.access_point_prefix_length,
            ssid=self.access_point_ssid,
            connection_name=self.access_point_connection_name,
            hostname=self.local_hostname,
            country_code=self.wifi_country_code,
            stack=self.network_stack,
            api_port=self.port or 8000,
            enabled=self.network_enabled,
        )
        pins = [
            pin
            for pin in (
                self.mode_button_pin,
                self.solo_led_pin,
                self.networked_led_pin,
                self.paired_led_pin,
            )
            if pin is not None
        ]
        if any(isinstance(pin, bool) or not isinstance(pin, int) or pin < 0 for pin in pins):
            raise ValueError("GPIO pins must be non-negative integers or None")
        if len(set(pins)) != len(pins):
            raise ValueError("GPIO pins must be distinct")
        if (
            isinstance(self.gpio_debounce_ms, bool)
            or not isinstance(self.gpio_debounce_ms, int)
            or self.gpio_debounce_ms < 0
        ):
            raise ValueError("gpio_debounce_ms must not be negative")
        if (
            isinstance(self.pairing_ttl_seconds, bool)
            or not isinstance(self.pairing_ttl_seconds, (int, float))
            or not math.isfinite(float(self.pairing_ttl_seconds))
            or self.pairing_ttl_seconds <= 0
        ):
            raise ValueError("pairing_ttl_seconds must be positive")
        if (
            isinstance(self.pairing_code_length, bool)
            or not isinstance(self.pairing_code_length, int)
            or not 6 <= self.pairing_code_length <= 16
        ):
            raise ValueError("pairing_code_length must be between 6 and 16")
        if (
            isinstance(self.controller_health_timeout_seconds, bool)
            or not isinstance(self.controller_health_timeout_seconds, (int, float))
            or not math.isfinite(float(self.controller_health_timeout_seconds))
            or self.controller_health_timeout_seconds <= 0
        ):
            raise ValueError("controller_health_timeout_seconds must be positive")
        if self.preview_width <= 0 or self.preview_height <= 0:
            raise ValueError("preview dimensions must be positive")
        if (
            self.max_fallback_upload_bytes <= 0
            or self.max_remote_crop_upload_bytes <= 0
        ):
            raise ValueError("image upload limits must be positive")
        if self.library_quota_bytes <= 0 or self.library_quota_observations <= 0:
            raise ValueError("library quotas must be positive")
        if self.save_deduplication_seconds < 0 or self.demo_save_deduplication_seconds < 0:
            raise ValueError("deduplication windows must not be negative")
        if self.stable_checks < 2:
            raise ValueError("stable_checks must be at least 2")
        for label in self.eligible_labels:
            if not isinstance(label, str) or not label.strip():
                raise ValueError("eligible_labels must contain non-empty strings")
        if self.llm_backend not in {"auto", "llama-cpp-python", "llama-cli", "disabled"}:
            raise ValueError("llm_backend must be auto, llama-cpp-python, llama-cli, or disabled")
        if (
            not isinstance(self.llama_cli_path, str)
            or not self.llama_cli_path.strip()
            or any(character in self.llama_cli_path for character in "\x00\r\n")
        ):
            raise ValueError("llama_cli_path must be a non-empty executable name or path")
        for name, value in (
            ("llm_context_tokens", self.llm_context_tokens),
            ("llm_threads", self.llm_threads),
            ("llm_batch_size", self.llm_batch_size),
            ("llm_max_tokens", self.llm_max_tokens),
            ("voice_sample_rate", self.voice_sample_rate),
            ("voice_chunk_ms", self.voice_chunk_ms),
            ("voice_silence_rms", self.voice_silence_rms),
            ("voice_max_audio_bytes", self.voice_max_audio_bytes),
            ("weed_max_upload_bytes", self.weed_max_upload_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        for name, value in (
            ("llm_temperature", self.llm_temperature),
            ("llm_timeout_seconds", self.llm_timeout_seconds),
            ("voice_start_timeout_seconds", self.voice_start_timeout_seconds),
            ("voice_short_silence_seconds", self.voice_short_silence_seconds),
            ("voice_long_silence_seconds", self.voice_long_silence_seconds),
            ("voice_max_turn_seconds", self.voice_max_turn_seconds),
            ("voice_tts_timeout_seconds", self.voice_tts_timeout_seconds),
            ("weed_position_max_accuracy_m", self.weed_position_max_accuracy_m),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be a positive number")
        if not 0.0 <= self.llm_temperature <= 2.0:
            raise ValueError("llm_temperature must be between 0 and 2")
        if not 0.0 <= self.weed_confidence <= 1.0 or not 0.0 <= self.weed_nms_iou <= 1.0:
            raise ValueError("weed confidence and NMS thresholds must be between 0 and 1")
        if str(self.stt_provider).lower() not in {"vosk", "faster-whisper", "disabled"}:
            raise ValueError("unsupported stt_provider")
        if str(self.tts_provider).lower() not in {"piper", "disabled"}:
            raise ValueError("unsupported tts_provider")

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
        **overrides: object,
    ) -> "AppSettings":
        """Load transport settings used by the Phase 7 systemd unit.

        The normal Python API continues to use explicit ``AppSettings()``
        defaults.  Environment loading is opt-in for the service launcher so
        test clients and imported application factories cannot accidentally
        inherit a machine's network mode.
        """

        # An explicitly supplied empty mapping is a useful deterministic way
        # to request defaults in tests and embedding callers.  Do not replace
        # it with the process environment merely because it is empty.
        values = dict(os.environ if environ is None else environ)

        def value(name: str, default: object, *, environment_name: str | None = None) -> object:
            if name in overrides:
                return overrides[name]
            key = environment_name or f"BOTANIKA_{name.upper()}"
            return values.get(key, default)

        network_enabled = _parse_bool(
            value("network_enabled", False),
            "BOTANIKA_NETWORK_ENABLED",
        )
        host_default = "0.0.0.0" if network_enabled else "127.0.0.1"
        loopback_default = not network_enabled
        return cls(
            host=str(value("host", host_default)),
            port=_parse_int(value("port", 8000), "BOTANIKA_PORT"),
            loopback_only=_parse_bool(
                value("loopback_only", loopback_default),
                "BOTANIKA_LOOPBACK_ONLY",
            ),
            network_enabled=network_enabled,
            tunnel_enabled=_parse_bool(
                value("tunnel_enabled", False, environment_name="BOTANIKA_TUNNEL_ENABLED"),
                "BOTANIKA_TUNNEL_ENABLED",
            ),
            cloudflared_path=str(
                value(
                    "cloudflared_path",
                    "/usr/local/bin/cloudflared",
                    environment_name="BOTANIKA_CLOUDFLARED_PATH",
                )
            ).strip(),
            cloudflared_name=_parse_optional_text(
                value(
                    "cloudflared_name",
                    None,
                    environment_name="BOTANIKA_CLOUDFLARED_NAME",
                )
            ),
            tunnel_startup_timeout_seconds=_parse_float(
                value(
                    "tunnel_startup_timeout_seconds",
                    15.0,
                    environment_name="BOTANIKA_TUNNEL_STARTUP_TIMEOUT_SECONDS",
                ),
                "BOTANIKA_TUNNEL_STARTUP_TIMEOUT_SECONDS",
            ),
            access_point_interface=str(
                value(
                    "access_point_interface",
                    value("ap_interface", "wlan0"),
                    environment_name="BOTANIKA_AP_INTERFACE",
                )
            ),
            access_point_address=str(
                value(
                    "access_point_address",
                    value("ap_address", "192.168.50.1"),
                    environment_name="BOTANIKA_AP_ADDRESS",
                )
            ),
            access_point_prefix_length=_parse_int(
                value(
                    "access_point_prefix_length",
                    value("ap_prefix_length", 24),
                    environment_name="BOTANIKA_AP_PREFIX_LENGTH",
                ),
                "BOTANIKA_AP_PREFIX_LENGTH",
            ),
            access_point_ssid=str(
                value(
                    "access_point_ssid",
                    value("ap_ssid", "Botanika"),
                    environment_name="BOTANIKA_AP_SSID",
                )
            ),
            access_point_connection_name=str(
                value(
                    "access_point_connection_name",
                    value("ap_connection_name", "botanika-ap"),
                    environment_name="BOTANIKA_AP_CONNECTION_NAME",
                )
            ),
            local_hostname=str(
                value(
                    "local_hostname",
                    value("ap_hostname", "botanika.home.arpa"),
                    environment_name="BOTANIKA_AP_HOSTNAME",
                )
            ),
            wifi_country_code=str(
                value(
                    "wifi_country_code",
                    value("ap_country_code", "IN"),
                    environment_name="BOTANIKA_AP_COUNTRY_CODE",
                )
            ),
            network_stack=str(
                value(
                    "network_stack",
                    value("ap_stack", "auto"),
                    environment_name="BOTANIKA_AP_STACK",
                )
            ).lower(),
            mode_button_pin=_parse_optional_int(
                value("mode_button_pin", None, environment_name="BOTANIKA_MODE_BUTTON_PIN"),
                "BOTANIKA_MODE_BUTTON_PIN",
            ),
            solo_led_pin=_parse_optional_int(
                value("solo_led_pin", None, environment_name="BOTANIKA_SOLO_LED_PIN"),
                "BOTANIKA_SOLO_LED_PIN",
            ),
            networked_led_pin=_parse_optional_int(
                value("networked_led_pin", None, environment_name="BOTANIKA_NETWORKED_LED_PIN"),
                "BOTANIKA_NETWORKED_LED_PIN",
            ),
            paired_led_pin=_parse_optional_int(
                value("paired_led_pin", None, environment_name="BOTANIKA_PAIRED_LED_PIN"),
                "BOTANIKA_PAIRED_LED_PIN",
            ),
            gpio_debounce_ms=_parse_int(
                value("gpio_debounce_ms", 250, environment_name="BOTANIKA_GPIO_DEBOUNCE_MS"),
                "BOTANIKA_GPIO_DEBOUNCE_MS",
            ),
            pairing_ttl_seconds=_parse_float(
                value("pairing_ttl_seconds", 300.0, environment_name="BOTANIKA_PAIRING_TTL_SECONDS"),
                "BOTANIKA_PAIRING_TTL_SECONDS",
            ),
            pairing_code_length=_parse_int(
                value("pairing_code_length", 8, environment_name="BOTANIKA_PAIRING_CODE_LENGTH"),
                "BOTANIKA_PAIRING_CODE_LENGTH",
            ),
            controller_health_timeout_seconds=_parse_float(
                value(
                    "controller_health_timeout_seconds",
                    45.0,
                    environment_name="BOTANIKA_CONTROLLER_HEALTH_TIMEOUT_SECONDS",
                ),
                "BOTANIKA_CONTROLLER_HEALTH_TIMEOUT_SECONDS",
            ),
            max_remote_crop_upload_bytes=_parse_int(
                value(
                    "max_remote_crop_upload_bytes",
                    12 * 1024 * 1024,
                    environment_name="BOTANIKA_MAX_REMOTE_CROP_UPLOAD_BYTES",
                ),
                "BOTANIKA_MAX_REMOTE_CROP_UPLOAD_BYTES",
            ),
            database_path=_parse_path(
                value("database_path", DEFAULT_SQLITE_PATH, environment_name="BOTANIKA_DATABASE_PATH"),
                DEFAULT_SQLITE_PATH,
            ),
            temp_crops_dir=_parse_path(
                value(
                    "temp_crops_dir",
                    PROJECT_ROOT / "data" / "media" / "temp" / "phase6-crops",
                    environment_name="BOTANIKA_TEMP_CROPS_DIR",
                ),
                PROJECT_ROOT / "data" / "media" / "temp" / "phase6-crops",
            ),
            discoveries_dir=_parse_optional_path(
                value("discoveries_dir", None, environment_name="BOTANIKA_DISCOVERIES_DIR"),
            ),
            backup_dir=_parse_path(
                value("backup_dir", PROJECT_ROOT / "data" / "backups", environment_name="BOTANIKA_BACKUP_DIR"),
                PROJECT_ROOT / "data" / "backups",
            ),
            llm_model_path=_parse_path(value("llm_model_path", DEFAULT_LLM_MODEL, environment_name="BOTANIKA_LLM_MODEL_PATH"), DEFAULT_LLM_MODEL),
            llm_backend=str(value("llm_backend", "auto", environment_name="BOTANIKA_LLM_BACKEND")).lower(),
            llama_cli_path=str(value("llama_cli_path", "/usr/local/bin/llama-cli", environment_name="BOTANIKA_LLAMA_CLI_PATH")).strip(),
            llm_context_tokens=_parse_int(value("llm_context_tokens", 2048, environment_name="BOTANIKA_LLM_CONTEXT_TOKENS"), "BOTANIKA_LLM_CONTEXT_TOKENS"),
            llm_threads=_parse_int(value("llm_threads", 4, environment_name="BOTANIKA_LLM_THREADS"), "BOTANIKA_LLM_THREADS"),
            llm_batch_size=_parse_int(value("llm_batch_size", 128, environment_name="BOTANIKA_LLM_BATCH_SIZE"), "BOTANIKA_LLM_BATCH_SIZE"),
            llm_temperature=_parse_float(value("llm_temperature", 0.1, environment_name="BOTANIKA_LLM_TEMPERATURE"), "BOTANIKA_LLM_TEMPERATURE"),
            llm_max_tokens=_parse_int(value("llm_max_tokens", 256, environment_name="BOTANIKA_LLM_MAX_TOKENS"), "BOTANIKA_LLM_MAX_TOKENS"),
            llm_timeout_seconds=_parse_float(value("llm_timeout_seconds", 20.0, environment_name="BOTANIKA_LLM_TIMEOUT_SECONDS"), "BOTANIKA_LLM_TIMEOUT_SECONDS"),
            stt_provider=str(value("stt_provider", "vosk", environment_name="BOTANIKA_STT_PROVIDER")).lower(),
            stt_models_path=_parse_path(value("stt_models_path", DEFAULT_STT_MODELS, environment_name="BOTANIKA_STT_MODELS_PATH"), DEFAULT_STT_MODELS),
            stt_model_name=_parse_optional_text(value("stt_model_name", None, environment_name="BOTANIKA_STT_MODEL_NAME")),
            tts_provider=str(value("tts_provider", "piper", environment_name="BOTANIKA_TTS_PROVIDER")).lower(),
            tts_models_path=_parse_path(value("tts_models_path", DEFAULT_TTS_MODELS, environment_name="BOTANIKA_TTS_MODELS_PATH"), DEFAULT_TTS_MODELS),
            tts_model_name=_parse_optional_text(value("tts_model_name", None, environment_name="BOTANIKA_TTS_MODEL_NAME")),
            voice_sample_rate=_parse_int(value("voice_sample_rate", 16000, environment_name="BOTANIKA_VOICE_SAMPLE_RATE"), "BOTANIKA_VOICE_SAMPLE_RATE"),
            voice_chunk_ms=_parse_int(value("voice_chunk_ms", 80, environment_name="BOTANIKA_VOICE_CHUNK_MS"), "BOTANIKA_VOICE_CHUNK_MS"),
            voice_silence_rms=_parse_int(value("voice_silence_rms", 500, environment_name="BOTANIKA_VOICE_SILENCE_RMS"), "BOTANIKA_VOICE_SILENCE_RMS"),
            voice_start_timeout_seconds=_parse_float(value("voice_start_timeout_seconds", 5.0, environment_name="BOTANIKA_VOICE_START_TIMEOUT_SECONDS"), "BOTANIKA_VOICE_START_TIMEOUT_SECONDS"),
            voice_short_silence_seconds=_parse_float(value("voice_short_silence_seconds", 1.0, environment_name="BOTANIKA_VOICE_SHORT_SILENCE_SECONDS"), "BOTANIKA_VOICE_SHORT_SILENCE_SECONDS"),
            voice_long_silence_seconds=_parse_float(value("voice_long_silence_seconds", 5.0, environment_name="BOTANIKA_VOICE_LONG_SILENCE_SECONDS"), "BOTANIKA_VOICE_LONG_SILENCE_SECONDS"),
            voice_max_turn_seconds=_parse_float(value("voice_max_turn_seconds", 30.0, environment_name="BOTANIKA_VOICE_MAX_TURN_SECONDS"), "BOTANIKA_VOICE_MAX_TURN_SECONDS"),
            voice_max_audio_bytes=_parse_int(value("voice_max_audio_bytes", 8 * 1024 * 1024, environment_name="BOTANIKA_VOICE_MAX_AUDIO_BYTES"), "BOTANIKA_VOICE_MAX_AUDIO_BYTES"),
            voice_tts_timeout_seconds=_parse_float(value("voice_tts_timeout_seconds", 30.0, environment_name="BOTANIKA_VOICE_TTS_TIMEOUT_SECONDS"), "BOTANIKA_VOICE_TTS_TIMEOUT_SECONDS"),
            weed_manifest_path=_parse_path(value("weed_manifest_path", DEFAULT_WEED_MANIFEST, environment_name="BOTANIKA_WEED_MANIFEST_PATH"), DEFAULT_WEED_MANIFEST),
            weed_confidence=_parse_float(value("weed_confidence", 0.35, environment_name="BOTANIKA_WEED_CONFIDENCE"), "BOTANIKA_WEED_CONFIDENCE"),
            weed_nms_iou=_parse_float(value("weed_nms_iou", 0.45, environment_name="BOTANIKA_WEED_NMS_IOU"), "BOTANIKA_WEED_NMS_IOU"),
            weed_max_upload_bytes=_parse_int(value("weed_max_upload_bytes", 12 * 1024 * 1024, environment_name="BOTANIKA_WEED_MAX_UPLOAD_BYTES"), "BOTANIKA_WEED_MAX_UPLOAD_BYTES"),
            weed_position_max_accuracy_m=_parse_float(value("weed_position_max_accuracy_m", 100.0, environment_name="BOTANIKA_WEED_POSITION_MAX_ACCURACY_M"), "BOTANIKA_WEED_POSITION_MAX_ACCURACY_M"),
            **{
                key: value
                for key, value in overrides.items()
                if key not in {
                    "host",
                    "port",
                    "loopback_only",
                    "network_enabled",
                    "tunnel_enabled",
                    "cloudflared_path",
                    "cloudflared_name",
                    "tunnel_startup_timeout_seconds",
                    "ap_interface",
                    "ap_address",
                    "ap_prefix_length",
                    "ap_ssid",
                    "ap_connection_name",
                    "ap_hostname",
                    "ap_country_code",
                    "ap_stack",
                    "access_point_interface",
                    "access_point_address",
                    "access_point_prefix_length",
                    "access_point_ssid",
                    "access_point_connection_name",
                    "local_hostname",
                    "wifi_country_code",
                    "network_stack",
                    "mode_button_pin",
                    "solo_led_pin",
                    "networked_led_pin",
                    "paired_led_pin",
                    "gpio_debounce_ms",
                    "pairing_ttl_seconds",
                    "pairing_code_length",
                    "controller_health_timeout_seconds",
                    "max_remote_crop_upload_bytes",
                    "database_path",
                    "temp_crops_dir",
                    "discoveries_dir",
                    "backup_dir",
                    "llm_model_path",
                    "llm_backend",
                    "llama_cli_path",
                    "llm_context_tokens",
                    "llm_threads",
                    "llm_batch_size",
                    "llm_temperature",
                    "llm_max_tokens",
                    "llm_timeout_seconds",
                    "stt_provider",
                    "stt_models_path",
                    "stt_model_name",
                    "tts_provider",
                    "tts_models_path",
                    "tts_model_name",
                    "voice_sample_rate",
                    "voice_chunk_ms",
                    "voice_silence_rms",
                    "voice_start_timeout_seconds",
                    "voice_short_silence_seconds",
                    "voice_long_silence_seconds",
                    "voice_max_turn_seconds",
                    "voice_max_audio_bytes",
                    "voice_tts_timeout_seconds",
                    "weed_manifest_path",
                    "weed_confidence",
                    "weed_nms_iou",
                    "weed_max_upload_bytes",
                    "weed_position_max_accuracy_m",
                }
            },
        )


def _parse_bool(value: object, name: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _parse_int(value: object, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _parse_float(value: object, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc


def _parse_optional_int(value: object, name: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return _parse_int(value, name)


def _parse_optional_text(value: object) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def _parse_path(value: object, default: Path) -> Path:
    text = str(value).strip() if value is not None else ""
    return Path(text) if text else Path(default)


def _parse_optional_path(value: object) -> Path | None:
    text = str(value).strip() if value is not None else ""
    return Path(text) if text else None
