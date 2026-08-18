from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from placepulse.api.schemas import (
    LocationData,
    PlaceView,
    SelectionView,
    VisitView,
)
from placepulse.config import Settings


@dataclass(frozen=True)
class Candidate:
    place: PlaceView
    confident: bool
    center_inside: bool


class LocationService:
    def __init__(self, engine: AsyncEngine, settings: Settings) -> None:
        self._engine = engine
        self._settings = settings

    async def resolve(
        self,
        *,
        user_id: uuid.UUID,
        latitude: float,
        longitude: float,
        accuracy_meters: float,
    ) -> LocationData:
        if accuracy_meters > self._settings.max_location_accuracy_meters:
            return self._result("low_accuracy", "ACCURACY_TOO_LOW")

        async with self._engine.begin() as connection:
            candidates = await self._candidates(
                connection,
                latitude=latitude,
                longitude=longitude,
                accuracy_meters=accuracy_meters,
            )
            confident = [candidate for candidate in candidates if candidate.confident]
            uncertain = [candidate.place for candidate in candidates if not candidate.confident]
            uncertain.sort(key=lambda place: (place.name.casefold(), str(place.id)))

            if not confident:
                if uncertain:
                    return self._result(
                        "ambiguous",
                        "ACCURACY_OVERLAPS_BOUNDARY",
                        uncertain_places=uncertain,
                    )
                await self._close_active(connection, user_id)
                return self._result("unknown", "NO_KNOWN_PLACE")

            path = self._single_chain(confident)
            if path is None:
                return self._result(
                    "ambiguous",
                    "OVERLAPPING_PLACE_HIERARCHIES",
                    uncertain_places=uncertain,
                )

            selected = path[0]
            visit = await self._transition_visit(connection, user_id, selected.id)
            selection = (
                SelectionView(
                    strategy="deepest_confident_containing",
                    reason_code="PARENT_SELECTED_FOR_ACCURACY",
                )
                if uncertain
                else SelectionView(
                    strategy="deepest_confident_containing",
                    reason_code="DEEPEST_CONFIDENT_PLACE",
                )
            )
            return LocationData(
                status="resolved",
                selected_place=selected,
                containment_path=path,
                uncertain_places=uncertain,
                selection=selection,
                visit=visit,
            )

    async def current(self, user_id: uuid.UUID) -> LocationData:
        async with self._engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT id, place_id, entered_at, exited_at FROM visits "
                        "WHERE user_id = :user_id AND exited_at IS NULL"
                    ),
                    {"user_id": user_id},
                )
            ).one_or_none()
            if row is None:
                return self._result("inactive", "NO_ACTIVE_VISIT")
            path = await self._path_to_root(connection, row.place_id)
            if not path:
                return self._result("inactive", "NO_ACTIVE_VISIT")
            return LocationData(
                status="resolved",
                selected_place=path[0],
                containment_path=path,
                uncertain_places=[],
                selection=SelectionView(
                    strategy="recorded_active_visit",
                    reason_code="RECORDED_ACTIVE_VISIT",
                ),
                visit=self._visit_view(row),
            )

    async def leave(self, user_id: uuid.UUID) -> LocationData:
        async with self._engine.begin() as connection:
            closed = await self._close_active(connection, user_id)
        return LocationData(
            status="inactive",
            selected_place=None,
            containment_path=[],
            uncertain_places=[],
            selection=SelectionView(
                strategy="recorded_active_visit",
                reason_code="VISIT_LEFT" if closed else "NO_ACTIVE_VISIT",
            ),
            visit=closed,
        )

    async def _candidates(
        self,
        connection: AsyncConnection,
        *,
        latitude: float,
        longitude: float,
        accuracy_meters: float,
    ) -> list[Candidate]:
        rows = (
            await connection.execute(
                text(
                    "WITH input AS ("
                    "SELECT ST_SetSRID(ST_Point(:longitude, :latitude), 4326) AS point"
                    ") SELECT places.id, places.name, places.osm_type, places.osm_id, "
                    "places.parent_place_id, "
                    "ST_Covers(places.boundary, input.point) center_inside, "
                    "CASE WHEN ST_Covers(places.boundary, input.point) THEN "
                    "ST_Distance(ST_Boundary(places.boundary)::geography, "
                    "input.point::geography) >= :accuracy ELSE FALSE END confident "
                    "FROM places, input WHERE ST_Covers(places.boundary, input.point) "
                    "OR ST_DWithin(places.boundary::geography, input.point::geography, :accuracy)"
                ),
                {
                    "longitude": longitude,
                    "latitude": latitude,
                    "accuracy": accuracy_meters,
                },
            )
        ).all()
        return [
            Candidate(
                place=PlaceView(
                    id=row.id,
                    name=row.name,
                    osm_type=row.osm_type,
                    osm_id=row.osm_id,
                    parent_place_id=row.parent_place_id,
                ),
                confident=bool(row.confident),
                center_inside=bool(row.center_inside),
            )
            for row in rows
        ]

    @staticmethod
    def _single_chain(confident: list[Candidate]) -> list[PlaceView] | None:
        by_id = {candidate.place.id: candidate.place for candidate in confident}
        parent_ids = {
            candidate.place.parent_place_id
            for candidate in confident
            if candidate.place.parent_place_id in by_id
        }
        leaves = [
            candidate.place for candidate in confident if candidate.place.id not in parent_ids
        ]
        if len(leaves) != 1:
            return None
        path: list[PlaceView] = []
        current: PlaceView | None = leaves[0]
        seen: set[uuid.UUID] = set()
        while current is not None and current.id not in seen:
            path.append(current)
            seen.add(current.id)
            current = (
                None if current.parent_place_id is None else by_id.get(current.parent_place_id)
            )
        if len(path) != len(confident):
            return None
        return path

    async def _path_to_root(
        self, connection: AsyncConnection, place_id: uuid.UUID
    ) -> list[PlaceView]:
        rows = (
            await connection.execute(
                text(
                    "WITH RECURSIVE place_path AS ("
                    "SELECT id, name, osm_type, osm_id, parent_place_id, 0 depth "
                    "FROM places WHERE id = :place_id UNION ALL "
                    "SELECT parent.id, parent.name, parent.osm_type, parent.osm_id, "
                    "parent.parent_place_id, place_path.depth + 1 "
                    "FROM places parent JOIN place_path ON parent.id = place_path.parent_place_id "
                    "WHERE place_path.depth < 32"
                    ") SELECT id, name, osm_type, osm_id, parent_place_id "
                    "FROM place_path ORDER BY depth"
                ),
                {"place_id": place_id},
            )
        ).all()
        return [
            PlaceView(
                id=row.id,
                name=row.name,
                osm_type=row.osm_type,
                osm_id=row.osm_id,
                parent_place_id=row.parent_place_id,
            )
            for row in rows
        ]

    async def _transition_visit(
        self, connection: AsyncConnection, user_id: uuid.UUID, place_id: uuid.UUID
    ) -> VisitView:
        await self._lock_user(connection, user_id)
        active = (
            await connection.execute(
                text(
                    "SELECT id, place_id, entered_at, exited_at FROM visits "
                    "WHERE user_id = :user_id AND exited_at IS NULL FOR UPDATE"
                ),
                {"user_id": user_id},
            )
        ).one_or_none()
        if active is not None and active.place_id == place_id:
            return self._visit_view(active)
        if active is not None:
            await connection.execute(
                text("UPDATE visits SET exited_at = CURRENT_TIMESTAMP WHERE id = :visit_id"),
                {"visit_id": active.id},
            )
        row = (
            await connection.execute(
                text(
                    "INSERT INTO visits (id, user_id, place_id, entered_at) "
                    "VALUES (:id, :user_id, :place_id, CURRENT_TIMESTAMP) "
                    "RETURNING id, place_id, entered_at, exited_at"
                ),
                {"id": uuid.uuid4(), "user_id": user_id, "place_id": place_id},
            )
        ).one()
        return self._visit_view(row)

    async def _close_active(
        self, connection: AsyncConnection, user_id: uuid.UUID
    ) -> VisitView | None:
        await self._lock_user(connection, user_id)
        row = (
            await connection.execute(
                text(
                    "UPDATE visits SET exited_at = CURRENT_TIMESTAMP "
                    "WHERE user_id = :user_id AND exited_at IS NULL "
                    "RETURNING id, place_id, entered_at, exited_at"
                ),
                {"user_id": user_id},
            )
        ).one_or_none()
        return None if row is None else self._visit_view(row)

    @staticmethod
    async def _lock_user(connection: AsyncConnection, user_id: uuid.UUID) -> None:
        await connection.execute(
            text("SELECT id FROM users WHERE id = :user_id FOR UPDATE"),
            {"user_id": user_id},
        )

    @staticmethod
    def _visit_view(row: Any) -> VisitView:
        return VisitView(
            id=row.id,
            place_id=row.place_id,
            entered_at=row.entered_at,
            exited_at=row.exited_at,
        )

    @staticmethod
    def _result(
        status: str,
        reason: str,
        *,
        uncertain_places: list[PlaceView] | None = None,
    ) -> LocationData:
        return LocationData.model_validate(
            {
                "status": status,
                "selected_place": None,
                "containment_path": [],
                "uncertain_places": uncertain_places or [],
                "selection": {
                    "strategy": "deepest_confident_containing",
                    "reason_code": reason,
                },
                "visit": None,
            }
        )
