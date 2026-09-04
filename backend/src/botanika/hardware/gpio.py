"""Safe, debounced GPIO controls for the Phase 8 mode handoff.

The adapter is intentionally small and dependency-free at import time.  A
Raspberry Pi with ``RPi.GPIO`` can use the optional backend; development and
tests use :class:`MemoryGPIO` or the no-op backend.  Mode transitions remain
owned by the mode state machine, so a GPIO edge can never create a second
controller or bypass pairing.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol

from botanika.mode import Mode


class GPIOBackend(Protocol):
    """Minimal hardware contract used by :class:`ModeGPIOAdapter`."""

    available: bool

    def setup_input(self, pin: int, callback: Callable[[], None]) -> None: ...

    def setup_output(self, pin: int) -> None: ...

    def write(self, pin: int, value: bool) -> None: ...

    def cleanup(self) -> None: ...


@dataclass(frozen=True, slots=True)
class GPIOPinConfig:
    """Optional BCM pin assignments for the physical mode/status controls."""

    mode_button_pin: int | None = None
    solo_led_pin: int | None = None
    networked_led_pin: int | None = None
    paired_led_pin: int | None = None
    debounce_ms: int = 250

    def __post_init__(self) -> None:
        for name in (
            "mode_button_pin",
            "solo_led_pin",
            "networked_led_pin",
            "paired_led_pin",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative GPIO pin or None")
        if (
            isinstance(self.debounce_ms, bool)
            or not isinstance(self.debounce_ms, int)
            or self.debounce_ms < 0
        ):
            raise ValueError("GPIO debounce_ms must be a non-negative integer")
        led_pins = [
            pin
            for pin in (
                self.solo_led_pin,
                self.networked_led_pin,
                self.paired_led_pin,
            )
            if pin is not None
        ]
        if len(set(led_pins)) != len(led_pins):
            raise ValueError("status LED pins must be distinct")
        if self.mode_button_pin is not None and self.mode_button_pin in led_pins:
            raise ValueError("mode button pin must be distinct from status LED pins")

    @classmethod
    def from_settings(cls, settings: object) -> "GPIOPinConfig":
        return cls(
            mode_button_pin=_optional_pin(getattr(settings, "mode_button_pin", None)),
            solo_led_pin=_optional_pin(getattr(settings, "solo_led_pin", None)),
            networked_led_pin=_optional_pin(getattr(settings, "networked_led_pin", None)),
            paired_led_pin=_optional_pin(getattr(settings, "paired_led_pin", None)),
            debounce_ms=int(getattr(settings, "gpio_debounce_ms", 250)),
        )


class NullGPIO:
    """Safe development fallback when GPIO libraries or pins are absent."""

    available = False

    def __init__(self) -> None:
        self.values: dict[int, bool] = {}
        self.cleaned = False

    def setup_input(self, _pin: int, _callback: Callable[[], None]) -> None:
        return None

    def setup_output(self, pin: int) -> None:
        self.values.setdefault(pin, False)

    def write(self, pin: int, value: bool) -> None:
        self.values[pin] = bool(value)

    def cleanup(self) -> None:
        self.cleaned = True


class MemoryGPIO(NullGPIO):
    """Observable fake backend used by unit tests and software demos."""

    available = True

    def __init__(self) -> None:
        super().__init__()
        self.input_callback: Callable[[], None] | None = None

    def setup_input(self, _pin: int, callback: Callable[[], None]) -> None:
        self.input_callback = callback

    def press(self) -> None:
        if self.input_callback is not None:
            self.input_callback()


class RPiGPIOBackend:
    """Thin optional wrapper around the classic RPi.GPIO package."""

    available = True

    def __init__(self, module) -> None:
        self._gpio = module
        self._gpio.setmode(module.BCM)
        self._callbacks: list[int] = []

    @classmethod
    def try_create(cls) -> "RPiGPIOBackend | None":
        try:
            import RPi.GPIO as gpio  # type: ignore[import-not-found]
        except (ImportError, RuntimeError):
            return None
        return cls(gpio)

    def setup_input(self, pin: int, callback: Callable[[], None]) -> None:
        self._gpio.setup(pin, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
        self._gpio.add_event_detect(
            pin,
            self._gpio.FALLING,
            callback=lambda _channel: callback(),
            bouncetime=0,
        )
        self._callbacks.append(pin)

    def setup_output(self, pin: int) -> None:
        self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.LOW)

    def write(self, pin: int, value: bool) -> None:
        self._gpio.output(pin, self._gpio.HIGH if value else self._gpio.LOW)

    def cleanup(self) -> None:
        for pin in self._callbacks:
            try:
                self._gpio.remove_event_detect(pin)
            except RuntimeError:
                pass
        self._callbacks.clear()
        self._gpio.cleanup()


class ModeGPIOAdapter:
    """One debounced mode button and up to three status LEDs."""

    def __init__(
        self,
        config: GPIOPinConfig | object | None = None,
        *,
        on_toggle: Callable[[], Mode | str | object] | None = None,
        initial_mode: Mode | str = Mode.SOLO,
        backend: GPIOBackend | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if config is None:
            config = GPIOPinConfig()
        elif not isinstance(config, GPIOPinConfig):
            config = GPIOPinConfig.from_settings(config)
        self.config = config
        self._on_toggle = on_toggle
        self._clock = clock
        self._backend = backend or (
            RPiGPIOBackend.try_create() if self._has_pins else None
        ) or NullGPIO()
        self._mode = _as_mode(initial_mode)
        self._last_press_at: float | None = None
        self._started = False
        self._cleaned = False
        self._led_state: dict[str, bool] = {
            "solo": False,
            "networked": False,
            "paired": False,
        }

    @property
    def _has_pins(self) -> bool:
        return bool(
            self.config.mode_button_pin is not None
            or self.config.solo_led_pin is not None
            or self.config.networked_led_pin is not None
            or self.config.paired_led_pin is not None
        )

    @property
    def available(self) -> bool:
        return bool(getattr(self._backend, "available", False) and self._has_pins)

    @property
    def started(self) -> bool:
        return self._started

    @property
    def mode(self) -> Mode:
        return self._mode

    @property
    def led_state(self) -> dict[str, bool]:
        return dict(self._led_state)

    def start(self, mode: Mode | str | None = None) -> None:
        """Configure pins with outputs low before publishing the safe mode."""

        if self._started:
            if mode is not None:
                self.set_mode(mode)
            return
        for pin in (
            self.config.solo_led_pin,
            self.config.networked_led_pin,
            self.config.paired_led_pin,
        ):
            if pin is not None:
                self._backend.setup_output(pin)
                self._backend.write(pin, False)
        if self.config.mode_button_pin is not None:
            self._backend.setup_input(self.config.mode_button_pin, self.button_pressed)
        self._started = True
        self._cleaned = False
        self.set_mode(mode or self._mode)

    def set_mode(self, mode: Mode | str) -> None:
        self._mode = _as_mode(mode)
        values = {
            "solo": self._mode is Mode.SOLO,
            "networked": self._mode in (Mode.NETWORKED_UNPAIRED, Mode.NETWORKED_PAIRED),
            "paired": self._mode is Mode.NETWORKED_PAIRED,
        }
        self._led_state = values
        pins = {
            "solo": self.config.solo_led_pin,
            "networked": self.config.networked_led_pin,
            "paired": self.config.paired_led_pin,
        }
        for name, pin in pins.items():
            if pin is not None:
                self._backend.write(pin, values[name])

    def button_pressed(self, *, now: float | None = None) -> bool:
        """Handle one physical/software press; return false when debounced."""

        current = self._clock() if now is None else float(now)
        if (
            self._last_press_at is not None
            and current - self._last_press_at < self.config.debounce_ms / 1000.0
        ):
            return False
        self._last_press_at = current
        if self._on_toggle is None:
            return False
        result = self._on_toggle()
        if isinstance(result, (Mode, str)):
            self.set_mode(result)
        return True

    # Names used by software fallbacks and simple test doubles.
    press = button_pressed
    handle_button_press = button_pressed

    def cleanup(self) -> None:
        """Turn every LED off and release GPIO resources, safely and idempotently."""

        if self._cleaned:
            return
        for pin in (
            self.config.solo_led_pin,
            self.config.networked_led_pin,
            self.config.paired_led_pin,
        ):
            if pin is not None:
                try:
                    self._backend.write(pin, False)
                except Exception:
                    pass
        try:
            self._backend.cleanup()
        finally:
            self._led_state = {"solo": False, "networked": False, "paired": False}
            self._started = False
            self._cleaned = True


class SoftwareModeFallback:
    """Keyboard/API-friendly fallback that shares the physical callback."""

    def __init__(self, toggle: Callable[[], object]) -> None:
        self._toggle = toggle

    def press(self) -> object:
        return self._toggle()


def create_mode_gpio(
    settings: object,
    on_toggle: Callable[[], Mode | str | object],
    *,
    backend: GPIOBackend | None = None,
) -> ModeGPIOAdapter:
    """Create the configured adapter; absent pins always select safe fallback."""

    adapter: ModeGPIOAdapter | None = None
    try:
        adapter = ModeGPIOAdapter(
            GPIOPinConfig.from_settings(settings),
            on_toggle=on_toggle,
            initial_mode=Mode.SOLO,
            backend=backend,
        )
        adapter.start()
        return adapter
    except Exception:
        # A missing GPIO permission, occupied pin, or unavailable board
        # library must not prevent the Pi API from booting in safe SOLO mode.
        if adapter is not None:
            try:
                adapter.cleanup()
            except Exception:
                pass
        fallback = ModeGPIOAdapter(
            GPIOPinConfig(),
            on_toggle=on_toggle,
            initial_mode=Mode.SOLO,
            backend=NullGPIO(),
        )
        fallback.start()
        return fallback


def _optional_pin(value: object) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _as_mode(value: Mode | str) -> Mode:
    return value if isinstance(value, Mode) else Mode(str(value).upper())


__all__ = [
    "GPIOBackend",
    "GPIOPinConfig",
    "MemoryGPIO",
    "ModeGPIOAdapter",
    "NullGPIO",
    "RPiGPIOBackend",
    "SoftwareModeFallback",
    "create_mode_gpio",
]
