from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Optional

from django.conf import settings
from django.db import DatabaseError, connections

from ..services.env import get_db_prefix
from ..models import (
    EveAlliance,
    EveAssetItem,
    EveCloneBay,
    EveCorporation,
    EveImplant,
    EveItemBasket,
    EveJumpClone,
    EvePilot,
    EvePilotCloneSummary,
    EvePilotClonebook,
    EvePilotSkill,
    EvePilotSkillSummary,
    EvePilotSkillbook,
    EveRepository,
    EveSkillBasket,
)


def _is_int_identifier(identifier: int | str) -> bool:
    return isinstance(identifier, int) or str(identifier).isdigit()


def _rows_as_dicts(cursor) -> list[dict[str, Any]]:
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _one_row_as_dict(cursor) -> dict[str, Any] | None:
    columns = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip(columns, row))


def _rows_from_sql_variants(
    *,
    using: str,
    statements: tuple[str, ...],
    params: list[object],
) -> list[dict[str, Any]]:
    last_error: DatabaseError | None = None
    for statement in statements:
        try:
            connection = connections[using]
            with connection.cursor() as cursor:
                cursor.execute(statement, params)
                return _rows_as_dicts(cursor)
        except DatabaseError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _one_row_from_sql_variants(
    *,
    using: str,
    statements: tuple[str, ...],
    params: list[object],
) -> dict[str, Any] | None:
    last_error: DatabaseError | None = None
    for statement in statements:
        try:
            connection = connections[using]
            with connection.cursor() as cursor:
                cursor.execute(statement, params)
                return _one_row_as_dict(cursor)
        except DatabaseError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return None


class DjangoAuthRepository(EveRepository):
    """AUTH repository backed by SQL over configured DB alias."""

    app = "AUTH"

    def __init__(self, *, using: str = "default") -> None:
        self.using = using

    def resolve_alliance(self, identifier: int | str) -> Optional[EveAlliance]:
        connection = connections[self.using]
        with connection.cursor() as cursor:
            if _is_int_identifier(identifier):
                cursor.execute(
                    """
                    SELECT
                        id AS source_pk,
                        alliance_id,
                        alliance_name,
                        alliance_ticker,
                        executor_corp_id
                    FROM eveonline_eveallianceinfo
                    WHERE alliance_id = %s
                    LIMIT 1
                    """,
                    [int(identifier)],
                )
            else:
                value = str(identifier)
                cursor.execute(
                    """
                    SELECT
                        id AS source_pk,
                        alliance_id,
                        alliance_name,
                        alliance_ticker,
                        executor_corp_id
                    FROM eveonline_eveallianceinfo
                    WHERE LOWER(alliance_ticker) = LOWER(%s)
                       OR LOWER(alliance_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    [value, value],
                )
            row = _one_row_as_dict(cursor)
        if not row:
            return None
        return EveAlliance.from_record(
            row,
            source_app="AUTH",
            source_model="auth.alliance",
            raw=row,
        )

    def resolve_corporation(self, identifier: int | str) -> Optional[EveCorporation]:
        connection = connections[self.using]
        with connection.cursor() as cursor:
            if _is_int_identifier(identifier):
                cursor.execute(
                    """
                    SELECT
                        id AS source_pk,
                        corporation_id,
                        corporation_name,
                        corporation_ticker,
                        member_count,
                        ceo_id,
                        alliance_id
                    FROM eveonline_evecorporationinfo
                    WHERE corporation_id = %s
                    LIMIT 1
                    """,
                    [int(identifier)],
                )
            else:
                value = str(identifier)
                cursor.execute(
                    """
                    SELECT
                        id AS source_pk,
                        corporation_id,
                        corporation_name,
                        corporation_ticker,
                        member_count,
                        ceo_id,
                        alliance_id
                    FROM eveonline_evecorporationinfo
                    WHERE LOWER(corporation_ticker) = LOWER(%s)
                       OR LOWER(corporation_name) = LOWER(%s)
                    LIMIT 1
                    """,
                    [value, value],
                )
            row = _one_row_as_dict(cursor)
        if not row:
            return None
        return EveCorporation.from_record(
            row,
            source_app="AUTH",
            source_model="auth.corporation",
            raw=row,
        )

    def list_pilots(
        self,
        *,
        alliance_id: Optional[int] = None,
        corporation_id: Optional[int] = None,
    ) -> Iterable[EvePilot]:
        sql = """
            SELECT
                ec.character_id,
                ec.character_name,
                ec.corporation_id,
                ec.corporation_name,
                ec.corporation_ticker,
                ec.alliance_id,
                ec.alliance_name,
                ec.alliance_ticker,
                aco.user_id,
                CASE
                    WHEN up.main_character_id = ec.id THEN 1
                    ELSE 0
                END AS is_main
            FROM eveonline_evecharacter ec
            LEFT JOIN authentication_characterownership aco
                ON aco.character_id = ec.id
            LEFT JOIN authentication_userprofile up
                ON up.user_id = aco.user_id
        """
        params: list[object] = []
        clauses: list[str] = []
        if alliance_id is not None:
            clauses.append("ec.alliance_id = %s")
            params.append(int(alliance_id))
        if corporation_id is not None:
            clauses.append("ec.corporation_id = %s")
            params.append(int(corporation_id))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = _rows_as_dicts(cursor)
        for row in rows:
            yield EvePilot.from_record(
                row,
                source_app="AUTH",
                source_model="auth.character",
                raw=row,
            )

    def list_mains(
        self,
        *,
        alliance_id: Optional[int] = None,
        corporation_id: Optional[int] = None,
    ) -> Iterable[EvePilot]:
        sql = """
            SELECT
                ec.character_id,
                ec.character_name,
                ec.corporation_id,
                ec.corporation_name,
                ec.corporation_ticker,
                ec.alliance_id,
                ec.alliance_name,
                ec.alliance_ticker
            FROM authentication_userprofile up
            JOIN eveonline_evecharacter ec
                ON up.main_character_id = ec.id
            WHERE up.main_character_id IS NOT NULL
        """
        params: list[object] = []
        if alliance_id is not None:
            sql += " AND ec.alliance_id = %s"
            params.append(int(alliance_id))
        if corporation_id is not None:
            sql += " AND ec.corporation_id = %s"
            params.append(int(corporation_id))

        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = _rows_as_dicts(cursor)
        for row in rows:
            yield EvePilot.from_record(
                row,
                source_app="AUTH",
                source_model="auth.character",
                is_main=True,
                raw=row,
            )

    def list_pilot_assets(self, character_id: int) -> Iterable[EveAssetItem]:
        rows = _rows_from_sql_variants(
            using=self.using,
            statements=(
                """
                SELECT
                    ca.id AS source_pk,
                    ec.character_id,
                    ca.item_id,
                    ca.eve_type_id AS type_id,
                    et.name AS type_name,
                    et.eve_group_id AS group_id,
                    ca.quantity,
                    ca.is_blueprint_copy,
                    ca.is_singleton,
                    ca.location_flag,
                    ca.location_id,
                    loc.name AS location_name,
                    ca.name AS item_name
                FROM memberaudit_characterasset ca
                JOIN memberaudit_character mc
                    ON mc.id = ca.character_id
                JOIN eveonline_evecharacter ec
                    ON ec.id = mc.eve_character_id
                LEFT JOIN eveuniverse_evetype et
                    ON et.id = ca.eve_type_id
                LEFT JOIN memberaudit_location loc
                    ON loc.id = ca.location_id
                WHERE ec.character_id = %s
                ORDER BY ca.eve_type_id, ca.item_id
                """,
                """
                SELECT
                    ca.id AS source_pk,
                    ec.character_id,
                    ca.item_id,
                    ca.eve_type_id AS type_id,
                    ca.quantity,
                    ca.is_blueprint_copy,
                    ca.is_singleton,
                    ca.location_flag,
                    ca.location_id,
                    loc.name AS location_name,
                    ca.name AS item_name
                FROM memberaudit_characterasset ca
                JOIN memberaudit_character mc
                    ON mc.id = ca.character_id
                JOIN eveonline_evecharacter ec
                    ON ec.id = mc.eve_character_id
                LEFT JOIN memberaudit_location loc
                    ON loc.id = ca.location_id
                WHERE ec.character_id = %s
                ORDER BY ca.eve_type_id, ca.item_id
                """,
            ),
            params=[int(character_id)],
        )
        for row in rows:
            yield EveAssetItem.from_record(
                row,
                source_app="AUTH",
                source_model="memberaudit.asset",
                raw=row,
            )

    def get_pilot_asset_basket(
        self,
        character_id: int,
    ) -> Optional[EveItemBasket]:
        items = tuple(self.list_pilot_assets(character_id))
        if not items:
            return None
        return EveItemBasket(
            source_app="AUTH",
            source_model="memberaudit.asset_basket",
            source_pk=int(character_id),
            character_id=int(character_id),
            items=items,
            raw=None,
        )

    def get_pilot_skill_summary(
        self,
        character_id: int,
    ) -> Optional[EvePilotSkillSummary]:
        sql = """
            SELECT
                sp.character_id AS source_pk,
                ec.character_id,
                sp.total,
                sp.unallocated
            FROM memberaudit_characterskillpoints sp
            JOIN memberaudit_character mc
                ON mc.id = sp.character_id
            JOIN eveonline_evecharacter ec
                ON ec.id = mc.eve_character_id
            WHERE ec.character_id = %s
            LIMIT 1
        """
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, [int(character_id)])
            row = _one_row_as_dict(cursor)
        if not row:
            return None
        return EvePilotSkillSummary.from_record(
            row,
            source_app="AUTH",
            source_model="memberaudit.skillpoints",
            raw=row,
        )

    def list_pilot_skills(self, character_id: int) -> Iterable[EvePilotSkill]:
        sql = """
            SELECT
                cs.id AS source_pk,
                ec.character_id,
                cs.eve_type_id AS skill_id,
                cs.active_skill_level,
                cs.trained_skill_level,
                cs.skillpoints_in_skill
            FROM memberaudit_characterskill cs
            JOIN memberaudit_character mc
                ON mc.id = cs.character_id
            JOIN eveonline_evecharacter ec
                ON ec.id = mc.eve_character_id
            WHERE ec.character_id = %s
            ORDER BY cs.eve_type_id
        """
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, [int(character_id)])
            rows = _rows_as_dicts(cursor)
        for row in rows:
            yield EvePilotSkill.from_record(
                row,
                source_app="AUTH",
                source_model="memberaudit.skill",
                raw=row,
            )

    def get_pilot_skillbook(
        self,
        character_id: int,
    ) -> Optional[EvePilotSkillbook]:
        summary = self.get_pilot_skill_summary(character_id)
        skills = tuple(self.list_pilot_skills(character_id))
        if summary is None and not skills:
            return None
        if summary is None:
            summary = EvePilotSkillSummary.from_record(
                {"character_id": int(character_id), "source_pk": int(character_id)},
                source_app="AUTH",
                source_model="memberaudit.skillpoints",
                raw=None,
            )
        basket = EveSkillBasket(
            source_app="AUTH",
            source_model="memberaudit.skill",
            source_pk=int(character_id),
            character_id=int(character_id),
            skills=skills,
            raw=None,
        )
        return EvePilotSkillbook(
            source_app="AUTH",
            source_model="auth.skillbook",
            source_pk=int(character_id),
            character_id=int(character_id),
            summary=summary,
            basket=basket,
            raw=None,
        )

    def get_pilot_clone_summary(
        self,
        character_id: int,
    ) -> Optional[EvePilotCloneSummary]:
        sql = """
            SELECT
                ci.character_id AS source_pk,
                ec.character_id,
                ci.home_location_id,
                loc.name AS home_location_name,
                loc.eve_solar_system_id AS solar_system_id,
                loc.eve_type_id,
                loc.owner_id,
                ci.last_clone_jump_date,
                ci.last_station_change_date
            FROM memberaudit_charactercloneinfo ci
            JOIN memberaudit_character mc
                ON mc.id = ci.character_id
            JOIN eveonline_evecharacter ec
                ON ec.id = mc.eve_character_id
            LEFT JOIN memberaudit_location loc
                ON loc.id = ci.home_location_id
            WHERE ec.character_id = %s
            LIMIT 1
        """
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, [int(character_id)])
            row = _one_row_as_dict(cursor)
        if not row:
            return None
        return EvePilotCloneSummary.from_record(
            row,
            source_app="AUTH",
            source_model="memberaudit.clone_info",
            raw=row,
        )

    def _list_jump_clone_implants(
        self,
        character_id: int,
    ) -> dict[int, tuple[EveImplant, ...]]:
        sql = """
            SELECT
                jci.id AS source_pk,
                ec.character_id,
                jc.jump_clone_id,
                jci.eve_type_id AS implant_id
            FROM memberaudit_characterjumpcloneimplant jci
            JOIN memberaudit_characterjumpclone jc
                ON jc.id = jci.jump_clone_id
            JOIN memberaudit_character mc
                ON mc.id = jc.character_id
            JOIN eveonline_evecharacter ec
                ON ec.id = mc.eve_character_id
            WHERE ec.character_id = %s
            ORDER BY jc.jump_clone_id, jci.eve_type_id
        """
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, [int(character_id)])
            rows = _rows_as_dicts(cursor)

        grouped: dict[int, list[EveImplant]] = {}
        for row in rows:
            jump_clone_id = int(row["jump_clone_id"])
            implant = EveImplant.from_record(
                row,
                source_app="AUTH",
                source_model="memberaudit.jump_clone_implant",
                raw=row,
            )
            grouped.setdefault(jump_clone_id, []).append(implant)
        return {key: tuple(values) for key, values in grouped.items()}

    def list_pilot_jump_clones(self, character_id: int) -> Iterable[EveJumpClone]:
        sql = """
            SELECT
                jc.id AS source_pk,
                ec.character_id,
                jc.jump_clone_id,
                jc.name AS clone_name,
                jc.location_id,
                loc.name AS location_name,
                loc.eve_solar_system_id AS solar_system_id,
                loc.eve_type_id,
                loc.owner_id
            FROM memberaudit_characterjumpclone jc
            JOIN memberaudit_character mc
                ON mc.id = jc.character_id
            JOIN eveonline_evecharacter ec
                ON ec.id = mc.eve_character_id
            LEFT JOIN memberaudit_location loc
                ON loc.id = jc.location_id
            WHERE ec.character_id = %s
            ORDER BY jc.jump_clone_id
        """
        implants_by_clone = self._list_jump_clone_implants(character_id)
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, [int(character_id)])
            rows = _rows_as_dicts(cursor)
        for row in rows:
            clone = EveJumpClone.from_record(
                row,
                source_app="AUTH",
                source_model="memberaudit.jump_clone",
                raw=row,
            )
            implants = implants_by_clone.get(clone.jump_clone_id)
            if implants:
                clone = replace(clone, implants=implants)
            yield clone

    def list_pilot_current_implants(self, character_id: int) -> Iterable[EveImplant]:
        sql = """
            SELECT
                ci.id AS source_pk,
                ec.character_id,
                ci.eve_type_id AS implant_id
            FROM memberaudit_characterimplant ci
            JOIN memberaudit_character mc
                ON mc.id = ci.character_id
            JOIN eveonline_evecharacter ec
                ON ec.id = mc.eve_character_id
            WHERE ec.character_id = %s
            ORDER BY ci.eve_type_id
        """
        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, [int(character_id)])
            rows = _rows_as_dicts(cursor)
        for row in rows:
            yield EveImplant.from_record(
                row,
                source_app="AUTH",
                source_model="memberaudit.implant",
                raw=row,
            )

    def get_pilot_clonebook(
        self,
        character_id: int,
    ) -> Optional[EvePilotClonebook]:
        summary = self.get_pilot_clone_summary(character_id)
        jump_clones = tuple(self.list_pilot_jump_clones(character_id))
        current_implants = tuple(self.list_pilot_current_implants(character_id))
        if summary is None and not jump_clones and not current_implants:
            return None
        if summary is None:
            summary = EvePilotCloneSummary.from_record(
                {"character_id": int(character_id), "source_pk": int(character_id)},
                source_app="AUTH",
                source_model="memberaudit.clone_info",
                raw=None,
            )
        bay = EveCloneBay(
            source_app="AUTH",
            source_model="memberaudit.clone_bay",
            source_pk=int(character_id),
            character_id=int(character_id),
            jump_clones=jump_clones,
            current_implants=current_implants,
            raw=None,
        )
        return EvePilotClonebook(
            source_app="AUTH",
            source_model="auth.clonebook",
            source_pk=int(character_id),
            character_id=int(character_id),
            summary=summary,
            bay=bay,
            raw=None,
        )


class DjangoCubeRepository(EveRepository):
    """CUBE repository backed by SQL over configured DB alias."""

    app = "CUBE"

    def __init__(self, *, using: str = "default") -> None:
        self.using = using
        self.dbprefix = get_db_prefix("CUBE", using=self.using)

    def _table(self, name: str) -> str:
        return f"{self.dbprefix}{name}" if self.dbprefix else name

    def resolve_alliance(self, identifier: int | str) -> Optional[EveAlliance]:
        connection = connections[self.using]
        with connection.cursor() as cursor:
            if _is_int_identifier(identifier):
                cursor.execute(
                    """
                    SELECT
                        MIN(id) AS source_pk,
                        alliance_id,
                        alliance_name
                    FROM accounts_evecharacter
                    WHERE alliance_id = %s
                    GROUP BY alliance_id, alliance_name
                    LIMIT 1
                    """,
                    [int(identifier)],
                )
            else:
                value = str(identifier)
                cursor.execute(
                    """
                    SELECT
                        MIN(id) AS source_pk,
                        alliance_id,
                        alliance_name
                    FROM accounts_evecharacter
                    WHERE LOWER(alliance_name) = LOWER(%s)
                    GROUP BY alliance_id, alliance_name
                    LIMIT 1
                    """,
                    [value],
                )
            row = _one_row_as_dict(cursor)
        if not row:
            return None
        return EveAlliance.from_record(
            row,
            source_app="CUBE",
            source_model="cube.alliance",
            raw=row,
        )

    def resolve_corporation(self, identifier: int | str) -> Optional[EveCorporation]:
        connection = connections[self.using]
        with connection.cursor() as cursor:
            if _is_int_identifier(identifier):
                cursor.execute(
                    """
                    SELECT
                        MIN(id) AS source_pk,
                        corporation_id,
                        corporation_name
                    FROM accounts_evecharacter
                    WHERE corporation_id = %s
                    GROUP BY corporation_id, corporation_name
                    LIMIT 1
                    """,
                    [int(identifier)],
                )
            else:
                value = str(identifier)
                cursor.execute(
                    """
                    SELECT
                        MIN(id) AS source_pk,
                        corporation_id,
                        corporation_name
                    FROM accounts_evecharacter
                    WHERE LOWER(corporation_name) = LOWER(%s)
                    GROUP BY corporation_id, corporation_name
                    LIMIT 1
                    """,
                    [value],
                )
            row = _one_row_as_dict(cursor)
        if not row:
            return None
        return EveCorporation.from_record(
            row,
            source_app="CUBE",
            source_model="cube.corporation",
            raw=row,
        )

    def list_pilots(
        self,
        *,
        alliance_id: Optional[int] = None,
        corporation_id: Optional[int] = None,
    ) -> Iterable[EvePilot]:
        sql = """
            SELECT
                character_id,
                character_name,
                corporation_id,
                corporation_name,
                alliance_id,
                alliance_name,
                is_main,
                user_id
            FROM accounts_evecharacter
        """
        params: list[object] = []
        clauses: list[str] = []
        if alliance_id is not None:
            clauses.append("alliance_id = %s")
            params.append(int(alliance_id))
        if corporation_id is not None:
            clauses.append("corporation_id = %s")
            params.append(int(corporation_id))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = _rows_as_dicts(cursor)
        for row in rows:
            yield EvePilot.from_record(
                row,
                source_app="CUBE",
                source_model="cube.character",
                raw=row,
            )

    def list_mains(
        self,
        *,
        alliance_id: Optional[int] = None,
        corporation_id: Optional[int] = None,
    ) -> Iterable[EvePilot]:
        sql = """
            SELECT
                character_id,
                character_name,
                corporation_id,
                corporation_name,
                alliance_id,
                alliance_name,
                is_main,
                user_id
            FROM accounts_evecharacter
            WHERE is_main = TRUE
        """
        params: list[object] = []
        if alliance_id is not None:
            sql += " AND alliance_id = %s"
            params.append(int(alliance_id))
        if corporation_id is not None:
            sql += " AND corporation_id = %s"
            params.append(int(corporation_id))

        connection = connections[self.using]
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            rows = _rows_as_dicts(cursor)
        for row in rows:
            yield EvePilot.from_record(
                row,
                source_app="CUBE",
                source_model="cube.character",
                is_main=True,
                raw=row,
            )

    def list_pilot_assets(self, character_id: int) -> Iterable[EveAssetItem]:
        assets_table = self._table("character_assets")
        asset_types_table = self._table("asset_types")
        asset_locations_table = self._table("asset_locations")
        rows = _rows_from_sql_variants(
            using=self.using,
            statements=(
                f"""
                SELECT
                    ca.id AS source_pk,
                    ec.character_id,
                    ca.item_id,
                    ca.type_id,
                    COALESCE(ca.type_name, at.name) AS type_name,
                    at.group_id,
                    at.category_id,
                    ca.quantity,
                    ca.is_blueprint_copy,
                    ca.is_singleton,
                    ca.location_flag,
                    ca.location_id,
                    COALESCE(ca.location_name, al.name) AS location_name
                FROM {assets_table} ca
                JOIN accounts_evecharacter ec
                    ON ec.id = ca.character_id
                LEFT JOIN {asset_types_table} at
                    ON at.type_id = ca.type_id
                LEFT JOIN {asset_locations_table} al
                    ON al.location_id = ca.location_id
                WHERE ec.character_id = %s
                ORDER BY ca.type_id, ca.item_id
                """,
                f"""
                SELECT
                    ca.id AS source_pk,
                    ec.character_id,
                    ca.item_id,
                    ca.type_id,
                    ca.type_name,
                    ca.quantity,
                    ca.is_blueprint_copy,
                    ca.is_singleton,
                    ca.location_flag,
                    ca.location_id,
                    ca.location_name
                FROM {assets_table} ca
                JOIN accounts_evecharacter ec
                    ON ec.id = ca.character_id
                WHERE ec.character_id = %s
                ORDER BY ca.type_id, ca.item_id
                """,
            ),
            params=[int(character_id)],
        )
        for row in rows:
            yield EveAssetItem.from_record(
                row,
                source_app="CUBE",
                source_model="cube.character_asset",
                raw=row,
            )

    def get_pilot_asset_basket(
        self,
        character_id: int,
    ) -> Optional[EveItemBasket]:
        items = tuple(self.list_pilot_assets(character_id))
        if not items:
            return None
        return EveItemBasket(
            source_app="CUBE",
            source_model="cube.asset_basket",
            source_pk=int(character_id),
            character_id=int(character_id),
            items=items,
            raw=None,
        )

    def get_pilot_skill_summary(
        self,
        character_id: int,
    ) -> Optional[EvePilotSkillSummary]:
        skills_summary_table = self._table("character_skills_summary")
        row = _one_row_from_sql_variants(
            using=self.using,
            statements=(
                f"""
                SELECT
                    css.id AS source_pk,
                    ec.character_id,
                    css.total_sp,
                    css.unallocated_sp
                FROM {skills_summary_table} css
                JOIN accounts_evecharacter ec
                    ON ec.id = css.character_id
                WHERE ec.character_id = %s
                LIMIT 1
                """,
            ),
            params=[int(character_id)],
        )
        if not row:
            return None
        return EvePilotSkillSummary.from_record(
            row,
            source_app="CUBE",
            source_model="cube.character_skills_summary",
            raw=row,
        )

    def list_pilot_skills(self, character_id: int) -> Iterable[EvePilotSkill]:
        skills_table = self._table("character_skills")
        skill_types_table = self._table("skill_types")
        rows = _rows_from_sql_variants(
            using=self.using,
            statements=(
                f"""
                SELECT
                    cs.id AS source_pk,
                    ec.character_id,
                    cs.skill_id,
                    cs.active_skill_level,
                    cs.trained_skill_level,
                    cs.skillpoints_in_skill,
                    st.name AS skill_name,
                    st.group_id
                FROM {skills_table} cs
                JOIN accounts_evecharacter ec
                    ON ec.id = cs.character_id
                LEFT JOIN {skill_types_table} st
                    ON st.type_id = cs.skill_id
                WHERE ec.character_id = %s
                ORDER BY cs.skill_id
                """,
                f"""
                SELECT
                    cs.id AS source_pk,
                    ec.character_id,
                    cs.skill_id,
                    cs.active_skill_level,
                    cs.trained_skill_level,
                    cs.skillpoints_in_skill
                FROM {skills_table} cs
                JOIN accounts_evecharacter ec
                    ON ec.id = cs.character_id
                WHERE ec.character_id = %s
                ORDER BY cs.skill_id
                """,
            ),
            params=[int(character_id)],
        )
        for row in rows:
            yield EvePilotSkill.from_record(
                row,
                source_app="CUBE",
                source_model="cube.character_skill",
                raw=row,
            )

    def get_pilot_skillbook(
        self,
        character_id: int,
    ) -> Optional[EvePilotSkillbook]:
        summary = self.get_pilot_skill_summary(character_id)
        skills = tuple(self.list_pilot_skills(character_id))
        if summary is None and not skills:
            return None
        if summary is None:
            summary = EvePilotSkillSummary.from_record(
                {"character_id": int(character_id), "source_pk": int(character_id)},
                source_app="CUBE",
                source_model="cube.character_skills_summary",
                raw=None,
            )
        basket = EveSkillBasket(
            source_app="CUBE",
            source_model="cube.character_skill",
            source_pk=int(character_id),
            character_id=int(character_id),
            skills=skills,
            raw=None,
        )
        return EvePilotSkillbook(
            source_app="CUBE",
            source_model="cube.skillbook",
            source_pk=int(character_id),
            character_id=int(character_id),
            summary=summary,
            basket=basket,
            raw=None,
        )

    def get_pilot_clone_summary(
        self,
        character_id: int,
    ) -> Optional[EvePilotCloneSummary]:
        _ = character_id
        return None

    def list_pilot_jump_clones(self, character_id: int) -> Iterable[EveJumpClone]:
        _ = character_id
        return ()

    def list_pilot_current_implants(self, character_id: int) -> Iterable[EveImplant]:
        _ = character_id
        return ()

    def get_pilot_clonebook(
        self,
        character_id: int,
    ) -> Optional[EvePilotClonebook]:
        _ = character_id
        return None
