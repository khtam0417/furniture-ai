"""Synthetic demo fixtures. NOT real rooms, NOT AI output.

Images are simple drawings generated here and stamped 'SYNTHETIC DEMO'. Fixture analyses are
hand-written PhotoAnalysisOutput objects stored with method='fixture' so they can never be
mistaken for a live model run. The studio fixture includes a synthetic floor-plan label so the
demo can exercise the user-confirmation path for plan dimensions.
"""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

from .models import (
    AIExistingItem, AIFeature, AIFloorplanReading, AIGeometry, AIPhotoNote, AIScaleCue, AIScaleEstimate, AIWall,
    AIWallFeature, PhotoAnalysisOutput,
)

PINK = (236, 72, 153)
INK = (24, 24, 27)


def _canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (960, 640), (245, 240, 236))
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 959, 44], fill=INK)
    dr.text((16, 14), "SAMPLE IMAGE - not a real room - Furniture AI example", fill=PINK)
    dr.text((16, 600), f"{title}: {subtitle}", fill=INK)
    return im, dr


def _jpeg(im: Image.Image) -> bytes:
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=88)
    return out.getvalue()


def bedroom_images() -> list[tuple[str, bytes]]:
    imgs = []
    im, dr = _canvas("Bedroom view A", "window wall, radiator, existing desk")
    dr.polygon([(120, 520), (840, 520), (700, 420), (260, 420)], fill=(214, 200, 186))  # floor
    dr.rectangle([360, 140, 600, 330], outline=INK, width=4, fill=(200, 225, 240))  # window
    dr.rectangle([380, 360, 580, 410], outline=INK, width=3)  # radiator
    dr.rectangle([640, 330, 800, 450], outline=INK, width=3, fill=(160, 120, 90))  # desk
    imgs.append(("bedroom_view_a.jpg", _jpeg(im)))
    im, dr = _canvas("Bedroom view B", "door and closet on opposite wall")
    dr.polygon([(120, 520), (840, 520), (700, 420), (260, 420)], fill=(214, 200, 186))
    dr.rectangle([200, 150, 330, 470], outline=INK, width=4, fill=(230, 220, 210))  # door
    dr.rectangle([480, 150, 760, 470], outline=INK, width=4, fill=(235, 235, 235))  # closet
    dr.line([(620, 150), (620, 470)], fill=INK, width=3)
    imgs.append(("bedroom_view_b.jpg", _jpeg(im)))
    return imgs


def studio_images() -> list[tuple[str, bytes]]:
    imgs = []
    im, dr = _canvas("Studio view A", "kitchen run along one wall, entry door")
    dr.polygon([(80, 540), (880, 540), (740, 430), (220, 430)], fill=(210, 196, 180))
    dr.rectangle([100, 250, 420, 430], outline=INK, width=4, fill=(220, 220, 225))  # counters
    dr.rectangle([440, 160, 560, 430], outline=INK, width=4, fill=(230, 220, 210))  # entry door
    imgs.append(("studio_view_a.jpg", _jpeg(im)))
    im, dr = _canvas("Studio view B", "window wall and bathroom door")
    dr.polygon([(80, 540), (880, 540), (740, 430), (220, 430)], fill=(210, 196, 180))
    dr.rectangle([300, 130, 640, 330], outline=INK, width=4, fill=(200, 225, 240))
    dr.rectangle([700, 170, 820, 430], outline=INK, width=4, fill=(230, 220, 210))
    imgs.append(("studio_view_b.jpg", _jpeg(im)))
    return imgs


def studio_floorplan() -> tuple[str, bytes]:
    im = Image.new("RGB", (960, 640), (255, 255, 255))
    dr = ImageDraw.Draw(im)
    dr.rectangle([0, 0, 959, 44], fill=INK)
    dr.text((16, 14), "SYNTHETIC DEMO FLOOR PLAN - invented for testing, not any real building", fill=PINK)
    dr.rectangle([120, 100, 840, 560], outline=INK, width=6)
    dr.rectangle([120, 100, 380, 200], outline=INK, width=3)
    dr.text((140, 140), "KITCHEN", fill=INK)
    dr.rectangle([680, 100, 840, 300], outline=INK, width=3)
    dr.text((700, 190), "BATH", fill=INK)
    dr.text((420, 330), "LIVING / SLEEPING", fill=INK)
    dr.text((420, 350), "13'-6\" x 17'-0\"", fill=INK)
    dr.text((140, 590), "Plan 'DEMO-S1' (synthetic)", fill=INK)
    return "studio_floorplan_synthetic.jpg", _jpeg(im)


def bedroom_analysis() -> PhotoAnalysisOutput:
    return PhotoAnalysisOutput(
        room_type_seen="bedroom",
        per_photo=[
            AIPhotoNote(photo_index=0, shows="Window wall with radiator below; an existing desk in the corner.",
                        appears_same_room_as_others="yes"),
            AIPhotoNote(photo_index=1, shows="Opposite wall with entry door and a two-door closet.",
                        quality_issue="Floor edge near the closet is cut off.", appears_same_room_as_others="yes"),
        ],
        shape_guess="rectangular",
        features=[
            AIFeature(kind="window", wall_guess="north", photo_indices=[0], description="Single wide window"),
            AIFeature(kind="radiator", wall_guess="north", photo_indices=[0], description="Radiator under the window"),
            AIFeature(kind="door", wall_guess="south", photo_indices=[1], description="Entry door, swings inward"),
            AIFeature(kind="closet", wall_guess="south", photo_indices=[1], description="Two-door closet"),
        ],
        existing_items=[AIExistingItem(category="desk", description="Small wooden desk", photo_indices=[0])],
        scale_cues=[AIScaleCue(description="Interior door looks typical, but its exact size is unknown", photo_index=1)],
        coverage_gaps=["Wall D is not visible in either photo."],
        geometry=AIGeometry(
            status="mapped", reference_wall_a="Window wall with the radiator (synthetic)", shape="rectangular", corners_seen=3,
            walls=[
                AIWall(wall="A", description="window wall with radiator", visible="fully", photo_indices=[0], features=[
                    AIWallFeature(kind="window", start_frac=0.3, end_frac=0.7, photo_indices=[0]),
                    AIWallFeature(kind="radiator", start_frac=0.33, end_frac=0.67, depth_in_low=6, depth_in_high=8, photo_indices=[0])]),
                AIWall(wall="B", description="plain wall right of the window", visible="partly", photo_indices=[0, 1]),
                AIWall(wall="C", description="door and closet wall", visible="fully", photo_indices=[1], features=[
                    AIWallFeature(kind="door", start_frac=0.08, end_frac=0.3, photo_indices=[1]),
                    AIWallFeature(kind="closet", start_frac=0.45, end_frac=0.9, photo_indices=[1])]),
                AIWall(wall="D", description="wall left of the window", visible="not_seen"),
            ],
            scale=AIScaleEstimate(wall_a_length_in_low=126, wall_a_length_in_high=148, wall_b_length_in_low=132,
                                  wall_b_length_in_high=156, reasoning="Synthetic fixture values.",
                                  cues=[AIScaleCue(description="interior door, typical size (weak cue)", photo_index=1)]),
            missing_views=["A photo of wall D (left of the window) would confirm the outline."],
            reasoning="Synthetic fixture geometry for the demo; not derived from a real room.",
        ),
    )


def studio_analysis() -> PhotoAnalysisOutput:
    return PhotoAnalysisOutput(
        room_type_seen="studio",
        per_photo=[
            AIPhotoNote(photo_index=0, shows="Kitchen counters along one wall next to the entry door.",
                        appears_same_room_as_others="yes"),
            AIPhotoNote(photo_index=1, shows="Window wall and the bathroom door.", appears_same_room_as_others="yes"),
            AIPhotoNote(photo_index=2, shows="Floor plan drawing labeled DEMO-S1.", appears_same_room_as_others="unclear"),
        ],
        shape_guess="rectangular",
        features=[
            AIFeature(kind="kitchen", wall_guess="north", photo_indices=[0, 2], description="Kitchen run with counters"),
            AIFeature(kind="entry", wall_guess="north", photo_indices=[0], description="Entry door beside the kitchen"),
            AIFeature(kind="window", wall_guess="south", photo_indices=[1], description="Wide window"),
            AIFeature(kind="bathroom", wall_guess="east", photo_indices=[1, 2], description="Bathroom door"),
        ],
        floorplan_readings=[AIFloorplanReading(photo_index=2, plan_label="DEMO-S1", room_label="Living / Sleeping",
                                               dimension_text="13'-6\" x 17'-0\"")],
        untrusted_text_seen=["KITCHEN", "BATH", "LIVING / SLEEPING"],
        coverage_gaps=["Corner behind the camera in view B is not visible."],
        geometry=AIGeometry(
            status="mapped", reference_wall_a="Kitchen and entry wall (synthetic)", shape="rectangular", corners_seen=3,
            walls=[
                AIWall(wall="A", description="kitchen and entry wall", visible="fully", photo_indices=[0, 2], features=[
                    AIWallFeature(kind="kitchen", start_frac=0.0, end_frac=0.42, depth_in_low=24, depth_in_high=26, photo_indices=[0, 2]),
                    AIWallFeature(kind="entry", start_frac=0.5, end_frac=0.66, photo_indices=[0])]),
                AIWall(wall="B", description="bathroom door wall", visible="partly", photo_indices=[1], features=[
                    AIWallFeature(kind="bathroom_door", start_frac=0.1, end_frac=0.28, photo_indices=[1])]),
                AIWall(wall="C", description="window wall", visible="fully", photo_indices=[1], features=[
                    AIWallFeature(kind="window", start_frac=0.25, end_frac=0.75, photo_indices=[1])]),
                AIWall(wall="D", description="wall left of the kitchen", visible="partly", photo_indices=[0]),
            ],
            scale=AIScaleEstimate(wall_a_length_in_low=150, wall_a_length_in_high=172, wall_b_length_in_low=192,
                                  wall_b_length_in_high=214, reasoning="Synthetic fixture values.",
                                  cues=[AIScaleCue(description="entry door, typical size (weak cue)", photo_index=0),
                                        AIScaleCue(description="kitchen counter run", photo_index=0)]),
            reasoning="Synthetic fixture geometry for the demo; not derived from a real room.",
        ),
    )
