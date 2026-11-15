"""Typed web boundary: every action the page may send, validated before the session sees it.

There is deliberately no "run this command" action and no raw wheel-speed action: the page can ask for a
destination, a confirm, a stop, a re-arm, and setup steps. The session decides everything else."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ActionType = Literal["start_session", "continue", "confirm", "set_drive_mode", "cancel_destination", "choose_again", "estop",
                     "rearm", "recenter", "layout", "end_session",
                     "begin_eye_calibration", "target_shown", "cancel_calibration",
                     "begin_jaw_calibration", "cancel_jaw_calibration"]


class LayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    viewport_w: float = Field(gt=0, le=20000)
    viewport_h: float = Field(gt=0, le=20000)
    screen_w: float = Field(gt=0, le=20000)
    screen_h: float = Field(gt=0, le=20000)
    dpr: float = Field(gt=0, le=10)
    fullscreen: bool
    video: tuple[float, float, float, float] | None = None


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ActionType
    seq: int = Field(ge=0)
    session: str | None = Field(default=None, max_length=64)
    mode: Literal["mock", "live"] | None = None
    confirm: Literal["dwell", "key", "blink", "jaw"] | None = None
    forward_camera: int | None = Field(default=None, ge=0, le=16)
    eye_camera: int | None = Field(default=None, ge=0, le=16)
    layout: LayoutIn | None = None
    run: int | None = Field(default=None, ge=0)        # calibration run id
    target: int | None = Field(default=None, ge=0)     # calibration target index
    drive_mode: Literal["auto", "manual"] | None = None

    @model_validator(mode="after")
    def _required_fields(self) -> "Action":
        if self.type == "layout" and self.layout is None:
            raise ValueError("layout action needs layout")
        if self.type == "target_shown" and (self.run is None or self.target is None):
            raise ValueError("target_shown needs run and target")
        if self.type == "start_session" and self.mode == "live" and \
                self.forward_camera is not None and self.forward_camera == self.eye_camera:
            raise ValueError("the eye camera and the forward camera must be different cameras")
        return self

    def as_dict(self) -> dict:
        data = self.model_dump()
        if self.layout is not None:
            data["layout"] = self.layout.model_dump()
        return data


class Beat(BaseModel):
    """Heartbeat from the page over the WebSocket (about 10 a second). pointer = viewport fraction or None."""
    model_config = ConfigDict(extra="ignore")
    type: Literal["beat"]
    pointer: tuple[float, float] | None = None
