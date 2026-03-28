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
from fg import control_keyring
from fg import pki as fg_pki
from fgbg_common.snapshot import PilotSnapshot

REQUEST_TIMEOUT_SECONDS = 5
CONTROL_BASE_URL_FALLBACK = 'http://127.0.0.1:18080'


class BgSyncError(RuntimeError):
    """Raised for control transport or rejected operations."""


def _control_base_url() -> str:
    env_url = (
        os.getenv('MURMUR_CONTROL_URL', '').strip()
        or os.getenv('MURMUR_CONTROL_BASE_URL', '').strip()
    )
    if env_url:
        return env_url.rstrip('/')
    return (
        getattr(settings, 'MURMUR_CONTROL_URL', None)
        or getattr(settings, 'MURMUR_CONTROL_BASE_URL', None)
        or CONTROL_BASE_URL_FALLBACK
    ).rstrip('/')


def _control_timeout() -> int:
    return int(getattr(settings, 'MURMUR_CONTROL_TIMEOUT_SECONDS', REQUEST_TIMEOUT_SECONDS))


def _control_headers(*, content_type_json: bool = False, psk_override: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if content_type_json:
        headers['Content-Type'] = 'application/json'

    if psk_override:
        headers['X-FGBG-PSK'] = psk_override
        headers['X-Murmur-Control-PSK'] = psk_override
        return headers

    # Prefer youngest session key in FG keyring (normal mode).
    for key_id, secret in control_keyring.decrypt_active_keypairs(limit=1):
        headers['X-BG-KEY-ID'] = str(key_id)
        headers['X-FGBG-PSK'] = secret
        headers['X-Murmur-Control-PSK'] = secret
        return headers

    # Fallback: bootstrap PSK (installation / break-glass only).
    shared_secret = (os.getenv('BG_PSK', '').strip() or getattr(settings, 'BG_PSK', None) or '').strip()
    if shared_secret:
        headers['X-FGBG-PSK'] = shared_secret
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
        raise BgSyncError('Control response was not valid JSON') from exc

    if not isinstance(result, dict):
        raise BgSyncError('Control response shape is invalid')
    return result


def _request_json(
    path: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    requested_by: str | None = None,
    allow_not_found: bool = False,
    sync_keys: bool = True,
    base_url: str | None = None,
    psk: str | None = None,
) -> dict[str, Any]:
    url = f'{base_url or _control_base_url()}{path}'
    body = None
    if payload is not None:
        body = json.dumps(_control_envelope(payload, requested_by=requested_by)).encode('utf-8')
    request = Request(
        url,
        data=body,
        method=method,
        headers=_control_headers(content_type_json=payload is not None, psk_override=psk),
    )
    try:
        with urlopen(request, timeout=_control_timeout()) as response:
            raw = response.read()
            response_headers = dict(response.headers.items())
    except HTTPError as exc:
        error_reason = str(exc.reason)
        try:
            parsed_error = _decode_json_response(exc.read())
        except BgSyncError:
            parsed_error = {}

        if parsed_error:
            if (
                allow_not_found
                and exc.code == 404
                and str(parsed_error.get('status', '')).lower() == 'not_found'
            ):
                return parsed_error
            error_reason = str(parsed_error.get('message') or parsed_error.get('status') or error_reason)

        raise BgSyncError(f'Control request failed ({exc.code}): {error_reason}') from exc
    except URLError as exc:
        raise BgSyncError(f'Control endpoint unreachable: {exc.reason}') from exc

    result = _decode_json_response(raw)

    status = str(result.get('status', 'completed')).lower()
    allowed_statuses = {'accepted', 'completed', 'partial'}
    if allow_not_found:
        allowed_statuses.add('not_found')
    if status not in allowed_statuses:
        raise BgSyncError(str(result.get('message', 'control rejected request')))

    if sync_keys:
        _maybe_sync_key_from_response_headers(response_headers, requested_by=requested_by)

    return result


def _maybe_sync_key_from_response_headers(headers: dict[str, str], *, requested_by: str | None) -> None:
    key_id = str(headers.get('X-BG-KEY-ID') or '').strip()
    if not key_id:
        return
    if control_keyring.has_key_id(key_id):
        return
    pem = fg_pki.public_key_pem()
    if not pem:
        return
    try:
        response = _request_json(
            '/v1/control-keys/export',
            method='POST',
            payload={
                'key_id': key_id,
                'fg_public_key_pem': pem.decode('ascii'),
            },
            requested_by=requested_by,
            sync_keys=False,
        )
    except Exception:
        return
    encrypted_secret = response.get('encrypted_secret')
    if isinstance(encrypted_secret, str) and encrypted_secret:
        response_key_id = response.get('key_id') or key_id
        control_keyring.store_encrypted(key_id=str(response_key_id), secret_ciphertext_b64=encrypted_secret)


def _post_json(
    path: str,
    payload: dict[str, Any],
    *,
    requested_by: str | None = None,
    base_url: str | None = None,
    psk: str | None = None,
) -> dict[str, Any]:
    return _request_json(path, method='POST', payload=payload, requested_by=requested_by, base_url=base_url, psk=psk)


def _get_json(
    path: str,
    *,
    allow_not_found: bool = False,
    base_url: str | None = None,
    psk: str | None = None,
) -> dict[str, Any]:
    return _request_json(path, method='GET', allow_not_found=allow_not_found, base_url=base_url, psk=psk)


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


def _normalize_pilot_snapshot_payload(snapshot: PilotSnapshot | dict[str, Any]) -> dict[str, Any]:
    if isinstance(snapshot, PilotSnapshot):
        return snapshot.as_dict()
    if not isinstance(snapshot, dict):
        raise BgSyncError('pilot_snapshot must be a PilotSnapshot or dict payload')
    return PilotSnapshot.from_mapping(snapshot).as_dict()


class BgControlClient:
    """OO adapter for FG -> BG control and probe endpoints."""

    def __init__(self, *, base_url: str | None = None, psk: str | None = None):
        self._base_url = base_url.rstrip('/') if base_url else None
        self._psk = psk or None

    def base_url(self) -> str:
        return self._base_url or _control_base_url()

    def _post(self, path: str, payload: dict[str, Any], *, requested_by: str | None = None) -> dict[str, Any]:
        return _post_json(path, payload, requested_by=requested_by, base_url=self._base_url, psk=self._psk)

    def _get(self, path: str, *, allow_not_found: bool = False) -> dict[str, Any]:
        return _get_json(path, allow_not_found=allow_not_found, base_url=self._base_url, psk=self._psk)

    def bootstrap_control_key(self, *, requested_by: str | None = None) -> str | None:
        """Fetch the newest BG session key (encrypted to FG) and store it locally.

        This is intended for initial installation / recovery when FG does not yet
        have a usable session key. BG must still accept the bootstrap PSK for this
        call to succeed.
        """
        pem = fg_pki.public_key_pem()
        if not pem:
            raise BgSyncError('FG public key is not configured (FG_PUBLIC_KEY_PATH)')
        response = self._post(
            '/v1/control-keys/export',
            {
                'fg_public_key_pem': pem.decode('ascii'),
            },
            requested_by=requested_by,
        )
        encrypted_secret = response.get('encrypted_secret')
        key_id = response.get('key_id')
        if not (isinstance(encrypted_secret, str) and encrypted_secret and isinstance(key_id, str) and key_id):
            raise BgSyncError('Control key export response did not include key_id/encrypted_secret')
        control_keyring.store_encrypted(key_id=key_id, secret_ciphertext_b64=encrypted_secret)
        return key_id

    def list_servers(self) -> list[dict[str, Any]]:
        response = self._get('/v1/servers')
        servers = response.get('servers')
        if not isinstance(servers, list):
            raise BgSyncError('Server probe response did not include servers')
        return [server for server in servers if isinstance(server, dict)]

    def get_server_inventory(self, server_id: int, *, refresh: bool = False) -> dict[str, Any]:
        path = f'/v1/servers/{int(server_id)}/inventory'
        if refresh:
            path = f'{path}?refresh=1'
        response = self._get(path)
        inventory = response.get('inventory')
        if not isinstance(inventory, dict):
            raise BgSyncError('Server inventory response did not include inventory')
        return response

    def list_registrations(self) -> list[dict[str, Any]]:
        response = self._get('/v1/registrations')
        registrations = response.get('registrations')
        if not isinstance(registrations, list):
            raise BgSyncError('Registration probe response did not include registrations')
        return [registration for registration in registrations if isinstance(registration, dict)]

    def sync_murmur_registration(
        self,
        mumble_user,
        password: str | None = None,
        *,
        requested_by: str | None = None,
    ) -> int | None:
        response = self._post(
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
        response = self._post(
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
        response = self._get(f'/v1/pilots/{int(pkid)}', allow_not_found=True)
        if str(response.get('status', '')).lower() == 'not_found':
            return []
        registrations = response.get('registrations')
        if not isinstance(registrations, list):
            raise BgSyncError('Probe response did not include registrations')
        return [registration for registration in registrations if isinstance(registration, dict)]

    @staticmethod
    def _normalize_session_ids(session_ids: Iterable[int]) -> list[int]:
        normalized: list[int] = []
        for value in session_ids:
            try:
                session_id = int(value)
            except (TypeError, ValueError):
                raise BgSyncError(f'Invalid session_id in payload: {value!r}') from None
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

        response = self._post(
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
            from fg.crypto import is_available as crypto_available, encrypt_password
            if crypto_available():
                payload['encrypted_password'] = encrypt_password(password)
            else:
                payload['password'] = password
        response = self._post('/v1/password-reset', payload, requested_by=requested_by)
        resolved_password = _extract_password(response)
        if resolved_password is None:
            raise BgSyncError('Control response did not include password')
        return resolved_password, _extract_murmur_userid(response)

    def reset_password_for_user(
        self,
        user,
        password: str | None = None,
        *,
        pkid: int | None = None,
        requested_by: str | None = None,
    ) -> dict[str, Any]:
        """Send password reset to BG by user pkid — BG resolves server/registration."""
        resolved_pkid = int(pkid) if pkid is not None else int(user.pk)
        payload = {
            'pkid': resolved_pkid,
        }
        if password is not None:
            from fg.crypto import is_available as crypto_available, encrypt_password
            if crypto_available():
                payload['encrypted_password'] = encrypt_password(password)
            else:
                payload['password'] = password
        return self._post('/v1/password-reset', payload, requested_by=requested_by)

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
        response = self._post('/v1/registrations/contract-sync', payload, requested_by=requested_by)
        return MurmurContract.from_mapping(response).as_payload()

    def sync_access_rules(
        self,
        rules: Iterable[dict[str, Any]],
        *,
        requested_by: str | None = None,
        is_super: bool = True,
        pilot_snapshot: PilotSnapshot | dict[str, Any] | None = None,
        reconcile: bool = False,
        server_id: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload_rules: list[dict[str, Any]] = []
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: expected object')

            try:
                entity_id = int(rule['entity_id'])
            except (KeyError, TypeError, ValueError):
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: entity_id') from None

            entity_type = str(rule.get('entity_type', '') or '').strip()
            if entity_type not in {'alliance', 'corporation', 'pilot'}:
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: entity_type')

            deny = rule.get('deny')
            if not isinstance(deny, bool):
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: deny')
            acl_admin = rule.get('acl_admin', False)
            if not isinstance(acl_admin, bool):
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: acl_admin')
            if acl_admin and entity_type != 'pilot':
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: acl_admin requires pilot entity_type')
            if acl_admin and deny:
                raise BgSyncError(f'Invalid ACL rule payload at index {idx}: denied pilots cannot be acl_admin')

            payload_rules.append(
                {
                    'entity_id': entity_id,
                    'entity_type': entity_type,
                    'deny': deny,
                    'acl_admin': acl_admin,
                    'note': str(rule.get('note', '') or ''),
                    'created_by': str(rule.get('created_by', '') or ''),
                }
            )

        response = self._post(
            '/v1/access-rules/sync',
            {
                'is_super': bool(is_super),
                'rules': payload_rules,
            },
            requested_by=requested_by,
        )

        if pilot_snapshot is not None:
            snapshot_response = self._post(
                '/v1/pilot-snapshot/sync',
                {
                    'is_super': bool(is_super),
                    **_normalize_pilot_snapshot_payload(pilot_snapshot),
                },
                requested_by=requested_by,
            )
            response['pilot_snapshot'] = snapshot_response

        if reconcile:
            provision_payload: dict[str, Any] = {
                'dry_run': bool(dry_run),
                'reconcile': True,
            }
            if server_id is not None:
                provision_payload['server_id'] = int(server_id)
            provision_response = self._post(
                '/v1/provision',
                provision_payload,
                requested_by=requested_by,
            )
            response['provision'] = provision_response

        return response


def get_active_bg_clients() -> list[BgControlClient]:
    """Return a BgControlClient for each active BgEndpoint, or a single
    default client if no endpoints are configured."""
    from fg.models import BgEndpoint
    endpoints = list(BgEndpoint.objects.filter(is_active=True))
    if not endpoints:
        return [BgControlClient()]
    return [
        BgControlClient(base_url=ep.url, psk=ep.psk or None)
        for ep in endpoints
    ]


__all__ = [
    'BgSyncError',
    'BgControlClient',
    'get_active_bg_clients',
]
