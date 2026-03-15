"""Control client for fg/bg boundaries.

This module provides a black-box integration point for Murmur control operations.
FG should not call background internals directly.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils.timezone import now

from fg.contracts import MurmurContract

REQUEST_TIMEOUT_SECONDS = 5
CONTROL_BASE_URL_FALLBACK = 'http://127.0.0.1:8000'


class MurmurSyncError(RuntimeError):
    """Raised for control transport or rejected operations."""


def _control_base_url() -> str:
    return (
        getattr(settings, 'MURMUR_CONTROL_URL', None)
        or getattr(settings, 'MURMUR_CONTROL_BASE_URL', None)
        or CONTROL_BASE_URL_FALLBACK
    ).rstrip('/')


def _control_timeout() -> int:
    return int(getattr(settings, 'MURMUR_CONTROL_TIMEOUT_SECONDS', REQUEST_TIMEOUT_SECONDS))


def _control_headers(*, content_type_json: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type_json:
        headers['Content-Type'] = 'application/json'

    shared_secret = (
        getattr(settings, 'MURMUR_CONTROL_PSK', None)
        or getattr(settings, 'MURMUR_CONTROL_SHARED_SECRET', None)
        or ''
    ).strip()
    if shared_secret:
        headers['X-Murmur-Control-PSK'] = shared_secret
    return headers


def _control_envelope(payload: dict[str, Any], *, requested_by: str | None) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    requested_by_value = requested_by or 'system'
    return {
        'request_id': request_id,
        'requested_by': requested_by_value,
        'timestamp': now().isoformat(),
        'payload': payload,
    }


def _decode_json_response(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        result = json.loads(raw.decode('utf-8'))
    except ValueError as exc:
        raise MurmurSyncError('Control response was not valid JSON') from exc

    if not isinstance(result, dict):
        raise MurmurSyncError('Control response shape is invalid')
    return result


def _request_json(
    path: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    requested_by: str | None = None,
    allow_not_found: bool = False,
) -> dict[str, Any]:
    url = f'{_control_base_url()}{path}'
    body = None
    if payload is not None:
        body = json.dumps(_control_envelope(payload, requested_by=requested_by)).encode('utf-8')
    request = Request(
        url,
        data=body,
        method=method,
        headers=_control_headers(content_type_json=payload is not None),
    )
    try:
        with urlopen(request, timeout=_control_timeout()) as response:
            raw = response.read()
    except HTTPError as exc:
        error_reason = str(exc.reason)
        try:
            parsed_error = _decode_json_response(exc.read())
        except MurmurSyncError:
            parsed_error = {}

        if parsed_error:
            if (
                allow_not_found
                and exc.code == 404
                and str(parsed_error.get('status', '')).lower() == 'not_found'
            ):
                return parsed_error
            error_reason = str(parsed_error.get('message') or parsed_error.get('status') or error_reason)

        raise MurmurSyncError(f'Control request failed ({exc.code}): {error_reason}') from exc
    except URLError as exc:
        raise MurmurSyncError(f'Control endpoint unreachable: {exc.reason}') from exc

    result = _decode_json_response(raw)

    status = str(result.get('status', 'completed')).lower()
    allowed_statuses = {'accepted', 'completed'}
    if allow_not_found:
        allowed_statuses.add('not_found')
    if status not in allowed_statuses:
        raise MurmurSyncError(str(result.get('message', 'control rejected request')))

    return result


def _post_json(path: str, payload: dict[str, Any], *, requested_by: str | None = None) -> dict[str, Any]:
    return _request_json(path, method='POST', payload=payload, requested_by=requested_by)


def _get_json(path: str, *, allow_not_found: bool = False) -> dict[str, Any]:
    return _request_json(path, method='GET', allow_not_found=allow_not_found)


def _extract_murmur_userid(response: dict[str, Any]) -> int | None:
    for key in ('murmur_userid', 'pkid'):
        value = response.get(key)
        if isinstance(value, int):
            return value
    status = response.get('status')
    if isinstance(status, dict):
        value = status.get('murmur_userid')
        if isinstance(value, int):
            return value
    payload = response.get('payload')
    if isinstance(payload, dict):
        value = payload.get('murmur_userid') or payload.get('result')
        if isinstance(value, int):
            return value
    return None


def _extract_password(response: dict[str, Any]) -> str | None:
    for key in ('password', 'proposed_password', 'temporary_password', 'recommended_password'):
        value = response.get(key)
        if isinstance(value, str) and value:
            return value
    payload = response.get('payload')
    if isinstance(payload, dict):
        for key in ('password', 'proposed_password', 'temporary_password', 'recommended_password'):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    status = response.get('status')
    if isinstance(status, dict):
        for key in ('password', 'proposed_password', 'temporary_password', 'recommended_password'):
            value = status.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _sync_endpoint_payload(mumble_user, *, password: str | None = None) -> dict[str, Any]:
    payload = {
        'pkid': mumble_user.user_id,
        'server_name': mumble_user.server.name,
        'username': mumble_user.username,
        'display_name': mumble_user.display_name,
        'murmur_userid': mumble_user.mumble_userid,
    }
    if password is not None:
        payload['password'] = password
    return payload


class BgControlClient:
    """OO adapter for FG -> BG control and probe endpoints."""

    def list_servers(self) -> list[dict[str, Any]]:
        response = _get_json('/v1/servers')
        servers = response.get('servers')
        if not isinstance(servers, list):
            raise MurmurSyncError('Server probe response did not include servers')
        return [server for server in servers if isinstance(server, dict)]

    def list_registrations(self) -> list[dict[str, Any]]:
        response = _get_json('/v1/registrations')
        registrations = response.get('registrations')
        if not isinstance(registrations, list):
            raise MurmurSyncError('Registration probe response did not include registrations')
        return [registration for registration in registrations if isinstance(registration, dict)]

    def sync_murmur_registration(
        self,
        mumble_user,
        password: str | None = None,
        *,
        requested_by: str | None = None,
    ) -> int | None:
        response = _post_json(
            '/v1/registrations/sync',
            _sync_endpoint_payload(mumble_user, password=password),
            requested_by=requested_by,
        )
        return _extract_murmur_userid(response)

    def unregister_murmur_registration(
        self,
        mumble_user,
        *,
        requested_by: str | None = None,
    ) -> bool:
        response = _post_json(
            '/v1/registrations/disable',
            {
                'pkid': mumble_user.user_id,
                'server_name': mumble_user.server.name,
                'username': mumble_user.username,
                'murmur_userid': mumble_user.mumble_userid,
            },
            requested_by=requested_by,
        )
        disabled = response.get('disabled')
        if isinstance(disabled, bool):
            return disabled
        status = response.get('status')
        if status in {'accepted', 'completed'}:
            return True
        return False

    def probe_murmur_registration(self, mumble_user) -> dict[str, Any] | None:
        for registration in self.probe_pilot_registrations(mumble_user.user_id):
            if not isinstance(registration, dict):
                continue
            if registration.get('server_name') == mumble_user.server.name:
                return registration
        return None

    def probe_pilot_registrations(self, pkid: int) -> list[dict[str, Any]]:
        response = _get_json(f'/v1/pilots/{int(pkid)}', allow_not_found=True)
        if str(response.get('status', '')).lower() == 'not_found':
            return []
        registrations = response.get('registrations')
        if not isinstance(registrations, list):
            raise MurmurSyncError('Probe response did not include registrations')
        return [registration for registration in registrations if isinstance(registration, dict)]

    @staticmethod
    def _normalize_session_ids(session_ids: Iterable[int]) -> list[int]:
        normalized: list[int] = []
        for value in session_ids:
            try:
                session_id = int(value)
            except (TypeError, ValueError):
                raise MurmurSyncError(f'Invalid session_id in payload: {value!r}') from None
            if session_id > 0:
                normalized.append(session_id)
        return normalized

    def sync_live_admin_membership(
        self,
        mumble_user,
        *,
        requested_by: str | None = None,
        session_ids: Iterable[int] | None = None,
    ) -> int:
        payload = {
            'pkid': mumble_user.user_id,
            'server_name': mumble_user.server.name,
            'admin': bool(mumble_user.is_mumble_admin),
            'groups': str(getattr(mumble_user, 'groups', '') or ''),
        }
        if session_ids is not None:
            payload['session_ids'] = self._normalize_session_ids(session_ids)

        response = _post_json(
            '/v1/admin-membership/sync',
            payload,
            requested_by=requested_by,
        )
        synced_sessions = response.get('synced_sessions')
        if isinstance(synced_sessions, int):
            return synced_sessions

        registration = self.probe_murmur_registration(mumble_user)
        if not registration:
            return 0
        active_session_count = registration.get('active_session_count')
        if isinstance(active_session_count, int):
            return active_session_count
        return 0

    def reset_murmur_password(
        self,
        mumble_user,
        password: str | None = None,
        *,
        requested_by: str | None = None,
    ) -> tuple[str, int | None]:
        payload = {
            'pkid': mumble_user.user_id,
            'server_name': mumble_user.server.name,
            'username': mumble_user.username,
        }
        if password is not None:
            payload['password'] = password
        response = _post_json('/v1/password-reset', payload, requested_by=requested_by)
        resolved_password = _extract_password(response)
        if resolved_password is None:
            raise MurmurSyncError('Control response did not include password')
        return resolved_password, _extract_murmur_userid(response)

    def sync_registration_contract(
        self,
        mumble_user,
        *,
        evepilot_id: int | str | None = None,
        corporation_id: int | str | None = None,
        alliance_id: int | str | None = None,
        kdf_iterations: int | str | None = None,
        requested_by: str | None = None,
        is_super: bool = False,
    ) -> dict[str, int | None]:
        request_contract = MurmurContract.from_mapping(
            {
                'evepilot_id': evepilot_id,
                'corporation_id': corporation_id,
                'alliance_id': alliance_id,
                'kdf_iterations': kdf_iterations,
            }
        )
        payload = {
            'pkid': mumble_user.user_id,
            'server_name': mumble_user.server.name,
            **request_contract.as_payload(),
            'is_super': bool(is_super),
        }
        response = _post_json('/v1/registrations/contract-sync', payload, requested_by=requested_by)
        return MurmurContract.from_mapping(response).as_payload()


__all__ = [
    'MurmurSyncError',
    'BgControlClient',
]
