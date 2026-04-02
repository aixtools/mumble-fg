from __future__ import annotations

from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as package_version

from django.conf import settings
from html import escape
from django.db import connections
from django.http import HttpRequest, HttpResponse, JsonResponse

from .services.eve_repository import get_repository
from .services.env import get_db_prefix

from .checks import (
    collect_connection_status,
    get_last_verify_messages,
    verify_connections,
)
from .services.ice_client import normalize_server_id
from .services.roster_cache import get_roster_payload, refresh_roster_cache


def _monitor_version() -> str:
    try:
        return package_version("monitor")
    except PackageNotFoundError:
        return "unknown"


_PANEL_SCRIPT = r"""  <script>
    var panelApp = null, panelPilots = null, panelOrdered = null;
    var panelView = 'list', panelPilot = null, panelRole = 'main';
    function groupByAllianceCorp(pilots) {
      var groups = {}, allianceIds = {};
      for (var i = 0; i < pilots.length; i++) {
        var p = pilots[i];
        var a = p.alliance_name || '';
        var c = p.corporation_name || '';
        if (!groups[a]) {
          groups[a] = {};
          allianceIds[a] = p.alliance_id || 0;
        }
        if (!groups[a][c]) groups[a][c] = [];
        groups[a][c].push(p);
      }
      var alliances = Object.keys(groups).sort(function(x, y) {
        if (x === '' && y !== '') return 1;
        if (x !== '' && y === '') return -1;
        var xl = x.toLowerCase(), yl = y.toLowerCase();
        return xl < yl ? -1 : xl > yl ? 1 : 0;
      });
      return alliances.map(function(a) {
        var corps = Object.keys(groups[a]).sort(function(x, y) {
          if (x === '' && y !== '') return 1;
          if (x !== '' && y === '') return -1;
          var xl = x.toLowerCase(), yl = y.toLowerCase();
          return xl < yl ? -1 : xl > yl ? 1 : 0;
        });
        return {
          alliance: a,
          alliance_id: allianceIds[a],
          corps: corps.map(function(c) {
            return {corp: c, pilots: groups[a][c]};
          })
        };
      });
    }
    function renderGrouped(groups, withClick, colorAlliances) {
      var html = '', idx = 0;
      groups.forEach(function(ag) {
        var aColor = (colorAlliances && ag.alliance_id > 1)
          ? 'color:red;' : '';
        html += '<div style="font-weight:bold;margin-top:.5rem;'
              + aColor + '">'
              + esc(ag.alliance || '\u2014') + '</div>';
        ag.corps.forEach(function(cg) {
          html += '<div style="padding-left:.75rem;color:#666">'
                + esc(cg.corp || '\u2014') + '</div>';
          cg.pilots.forEach(function(p) {
            var hasAlts = withClick && (
              (p.hasa && p.hasa.length) ||
              (p.alts && p.alts.length) ||
              (p.has_alts_count && p.has_alts_count > 0)
            );
            html += '<div style="padding-left:1.5rem">';
            if (hasAlts) {
              html += '<span style="font-weight:bold;color:#0000EE;'
                    + 'cursor:pointer" onclick="selectPilot('
                    + idx + ')">'
                    + esc(p.name) + '</span>';
            } else {
              html += esc(p.name)
                    + ' <span style="color:#080;cursor:pointer"'
                    + ' onclick="showDetails('
                    + idx + ')">details</span>';
            }
            html += '</div>';
            idx++;
          });
        });
      });
      return html;
    }
    function openPanel(app, role) {
      panelApp = app; panelRole = role;
      panelView = 'list'; panelPilot = null;
      panelPilots = null; panelOrdered = null;
      document.getElementById('pilot-panel')
        .classList.remove('hidden');
      renderPanel();
      var endpoint = '/monitor/status/pilots/?app=' + app;
      if (role === 'main') {
        endpoint = '/monitor/status/mains-with-alts/?app=' + app
          + '&lite=1';
      } else if (role === 'spy') {
        endpoint = '/monitor/status/spies/?app=' + app;
      } else if (role === 'orphan') {
        endpoint = '/monitor/status/orphans/?app=' + app;
      }
      fetch(endpoint)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (!data || data.ok === false) {
            panelPilots = [];
            renderPanel();
            return;
          }
          if (role === 'main') {
            panelPilots = data.mains || [];
          } else if (role === 'spy') {
            panelPilots = (data.spies || []).map(function(p) {
              return {
                name: p.name,
                character_id: p.character_id,
                alliance_name: p.alliance_name || '',
                alliance_id: 0,
                corporation_name: p.corporation_name || '',
                isa: 'spy',
                hasa: (p.alts || []).map(function(a) {
                  return {
                    name: a.name,
                    character_id: a.character_id,
                    alliance_name: a.alliance_name || '',
                    alliance_id: a.alliance_id || 0,
                    corporation_name: a.corporation_name || '',
                  };
                }),
              };
            });
          } else if (role === 'orphan') {
            panelPilots = (data.orphans || []).map(function(p) {
              return {
                name: p.name,
                character_id: p.character_id,
                alliance_name: p.alliance_name || '',
                alliance_id: 0,
                corporation_name: p.corporation_name || '',
                isa: 'orphan',
                hasa: [],
              };
            });
          } else {
            panelPilots = data.pilots || [];
          }
          renderPanel();
        });
    }
    function openIceUsers() {
      document.getElementById('pilot-panel')
        .classList.add('hidden');
      var title = document.getElementById('details-title');
      var body = document.getElementById('details-body');
      var area = document.getElementById('pilot-details');
      if (title) title.textContent = 'Mumble ICE Users';
      if (body) body.innerHTML = 'Loading\u2026';
      if (area) area.classList.remove('hidden');
      area.scrollIntoView({behavior:'smooth', block:'start'});
      fetch('/monitor/status/ice-users/')
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (!body) return;
          if (!data || data.ok === false) {
            body.innerHTML = '<p>ICE users unavailable.</p>';
            return;
          }
          var users = data.users || [];
          if (!users.length) {
            body.innerHTML = '<p>No users registered.</p>';
            return;
          }
          var cs = 'border:1px solid #ccc;padding:2px 6px;text-align:left';
          var html = '<table style="border-collapse:collapse;'
            + 'margin-top:.5rem;margin-bottom:.75rem;font-family:monospace">';
          html += '<tr>'
            + '<th style="' + cs + '">st</th>'
            + '<th style="' + cs + '">user</th>'
            + '<th style="' + cs + '">session</th>'
            + '<th style="' + cs + '">channel</th>'
            + '<th style="' + cs + '">role</th>'
            + '<th style="' + cs + '">cert_hash</th>'
            + '</tr>';
          users.forEach(function(u) {
            html += '<tr>'
              + '<td style="' + cs + '">' + esc(u.status || '-') + '</td>'
              + '<td style="' + cs + '">' + esc(u.user || '-') + '</td>'
              + '<td style="' + cs + '">' + esc(u.session || '-') + '</td>'
              + '<td style="' + cs + '">' + esc(u.channel_id || '-') + '</td>'
              + '<td style="' + cs + '">' + esc(u.roles || '-') + '</td>'
              + '<td style="' + cs + '">' + esc(u.cert_hash || '-') + '</td>'
              + '</tr>';
          });
          html += '</table>';
          body.innerHTML = html;
        })
        .catch(function() {
          if (body) body.innerHTML = '<p>ICE users unavailable.</p>';
        });
    }
    function panelBack() {
      if (panelView === 'detail') {
        panelView = 'list'; panelPilot = null;
        renderPanel();
      } else {
        document.getElementById('pilot-panel')
          .classList.add('hidden');
      }
    }
    function ensureMainAlts(pilot, done) {
      if (!pilot) {
        done(false);
        return;
      }
      if (pilot.hasa && pilot.hasa.length) {
        done(true);
        return;
      }
      if (!pilot.has_alts_count || pilot.has_alts_count <= 0) {
        done(false);
        return;
      }
      fetch('/monitor/status/main-alts/?app=' + panelApp
            + '&id=' + pilot.character_id)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          var alts = (data && data.alts) || [];
          pilot.hasa = alts.map(function(a) {
            return {
              name: a.name,
              character_id: a.character_id,
              alliance_name: a.alliance_name || '',
              alliance_id: a.alliance_id || 0,
              corporation_name: a.corporation_name || '',
            };
          });
          done(pilot.hasa.length > 0);
        })
        .catch(function() { done(false); });
    }
    function selectPilot(idx) {
      panelPilot = panelOrdered ? panelOrdered[idx] : null;
      if (panelPilot && panelRole === 'main'
          && (!panelPilot.hasa || !panelPilot.hasa.length)
          && panelPilot.has_alts_count
          && panelPilot.has_alts_count > 0) {
        ensureMainAlts(panelPilot, function(ok) {
          if (ok) {
            panelView = 'detail';
            renderPanel();
          }
        });
        return;
      }
      if (panelPilot && (!panelPilot.hasa || !panelPilot.hasa.length)
          && panelPilot.alts && panelPilot.alts.length) {
        panelPilot.hasa = panelPilot.alts.map(function(a) {
          return {
            name: a.name,
            character_id: a.character_id,
            alliance_name: a.alliance_name || '',
            alliance_id: a.alliance_id || 0,
            corporation_name: a.corporation_name || '',
          };
        });
      }
      if (!panelPilot || !panelPilot.hasa || !panelPilot.hasa.length)
        return;
      panelView = 'detail';
      renderPanel();
    }
    function renderPanel() {
      var title = document.getElementById('panel-title');
      var btn = document.getElementById('panel-back-btn');
      var body = document.getElementById('panel-body');
      var labels = {main: 'Mains', spy: 'Spies', orphan: 'Orphans'};
      if (panelView === 'detail' && panelPilot) {
        title.textContent = panelPilot.name;
        btn.textContent = 'Back';
        document.getElementById('panel-details-btn')
          .classList.remove('hidden');
        var html = '';
        if (panelRole === 'spy') {
          html += '<div style="font-weight:bold;margin-top:.25rem">'
                + esc(panelPilot.alliance_name || '\u2014') + '</div>';
          html += '<div style="padding-left:.75rem;color:#666">'
                + esc(panelPilot.corporation_name || '\u2014')
                + '</div>';
          html += '<div style="padding-left:1.5rem;font-weight:bold">'
                + esc(panelPilot.name) + '</div>';
          html += '<div style="margin-top:.5rem;font-size:.85em;'
                + 'color:#555">Alts:</div>';
          html += renderGrouped(
            groupByAllianceCorp(panelPilot.hasa), false, true);
        } else {
          html += '<ul style="padding:0;list-style:none;margin:0">';
          html += '<li style="font-weight:bold">'
                + esc(panelPilot.name) + '</li>';
          for (var i = 0; i < panelPilot.hasa.length; i++) {
            html += '<li style="padding-left:1rem">'
                  + esc(panelPilot.hasa[i].name) + '</li>';
          }
          html += '</ul>';
        }
        body.innerHTML = html;
        return;
      }
      document.getElementById('panel-details-btn')
        .classList.add('hidden');
      btn.textContent = 'Close';
      title.textContent = panelApp + ' ' + (labels[panelRole] || '');
      if (!panelPilots) {
        body.innerHTML = '<p>Loading\u2026</p>';
        return;
      }
      var pilots = panelPilots.filter(function(p) {
        return (p.isa || panelRole) === panelRole;
      });
      var withClick = panelRole !== 'orphan';
      var groups = groupByAllianceCorp(pilots);
      panelOrdered = [];
      groups.forEach(function(ag) {
        ag.corps.forEach(function(cg) {
          cg.pilots.forEach(function(p) { panelOrdered.push(p); });
        });
      });
      body.innerHTML = renderGrouped(
        groups, withClick, panelRole === 'spy');
    }
    function esc(s) {
      s = String((s === null || s === undefined) ? '' : s);
      return s.replace(/&/g, '&amp;')
               .replace(/</g, '&lt;')
               .replace(/>/g, '&gt;');
    }
    function fmtNum(n) {
      if (n === null || n === undefined) return '---';
      n = Math.floor(n);
      if (n < 1000) return String(n);
      if (n < 1000000) return Math.floor(n / 1000) + 'k';
      if (n < 1000000000)
        return Math.floor(n / 1000000) + 'm';
      return Math.floor(n / 1000000000) + 'b';
    }
    function fmtSP(n) {
      if (n === null || n === undefined) return '---';
      if (n < 4000000) return 'noob';
      return Math.floor(n / 1000000) + 'm';
    }
    function trunc8(s) {
      return s.length > 8 ? s.slice(0, 8) : s;
    }
    function renderWealthTable(pilot, wealth, meta) {
      var chars = [pilot];
      (pilot.hasa || []).forEach(function(a) {
        chars.push(a);
      });
      function getVal(c, key) {
        var w = wealth[String(c.character_id)];
        return (w && w[key] !== null
          && w[key] !== undefined) ? w[key] : null;
      }
      var cs = 'border:1px solid #ccc;padding:2px 4px';
      var s = '<table style="border-collapse:collapse;'
            + 'margin-top:.5rem;margin-right:2rem;'
            + 'margin-bottom:.75rem">';
      s += '<tr><th style="' + cs
         + ';text-align:left"></th>';
      s += '<th style="' + cs
         + ';text-align:right">Total</th>';
      chars.forEach(function(c, idx) {
        s += '<th style="' + cs
           + ';text-align:right;min-width:10ch">'
           + esc(idx === 0 ? c.name : trunc8(c.name)) + '</th>';
      });
      // Trailing spacer keeps right-side whitespace when scrolling wide tables.
      s += '<th style="min-width:2rem;padding:0;border:none"></th>';
      s += '</tr>';
      function sumOrNull(vals) {
        var t = 0, any = false;
        for (var i = 0; i < vals.length; i++) {
          if (vals[i] !== null) { t += vals[i]; any = true; }
        }
        return any ? t : null;
      }
      function makeRow(label, key, fmt, totalOverride) {
        if (!fmt) fmt = fmtNum;
        var vals = chars.map(function(c) {
          return getVal(c, key);
        });
        var total = (totalOverride !== null
          && totalOverride !== undefined)
          ? totalOverride : sumOrNull(vals);
        var r = '<tr><td style="' + cs + '">'
              + label + '</td>';
        r += '<td style="' + cs + ';text-align:right">'
           + fmt(total) + '</td>';
        vals.forEach(function(v) {
          r += '<td style="' + cs
             + ';text-align:right">'
             + fmt(v) + '</td>';
        });
        r += '<td style="min-width:2rem;padding:0;border:none"></td>';
        return r + '</tr>';
      }
      s += makeRow('Assets', 'assets', fmtNum, null);
      s += makeRow('Assets-ISK', 'assets_isk', fmtNum, null);
      s += makeRow('Wallet', 'wallet', fmtNum, null);
      s += makeRow('SP', 'sp', fmtSP, null);
      s += makeRow('Clones', 'clones', fmtNum, null);
      s += makeRow('Contacts', 'contacts', fmtNum,
        (meta && meta.contacts_total != null)
          ? meta.contacts_total : null);
      s += '</table>';
      return s;
    }
    function showDetails(idx) {
      var pilot = panelOrdered ? panelOrdered[idx] : null;
      if (!pilot) return;
      var title = document.getElementById('details-title');
      var body = document.getElementById('details-body');
      var area = document.getElementById('pilot-details');
      if (title) title.textContent = pilot.name;
      if (body) body.innerHTML = 'Loading\u2026';
      if (area) area.classList.remove('hidden');
      area.scrollIntoView({behavior: 'smooth', block: 'start'});
      if (panelRole === 'main'
          && (!pilot.hasa || !pilot.hasa.length)
          && pilot.has_alts_count && pilot.has_alts_count > 0) {
        ensureMainAlts(pilot, function(ok) {
          if (ok) {
            showDetails(idx);
            return;
          }
          if (body) body.innerHTML =
            '<p>Details unavailable.</p>';
        });
        return;
      }
      var chars = [pilot];
      (pilot.hasa || []).forEach(function(a) { chars.push(a); });
      var ids = chars.map(function(c) {
        return c.character_id;
      }).join(',');
      fetch('/monitor/status/pilot-wealth/?app='
            + panelApp + '&ids=' + ids)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (body) body.innerHTML =
            renderWealthTable(pilot, data.wealth || {}, data);
        })
        .catch(function() {
          if (body) body.innerHTML =
            '<p>Details unavailable.</p>';
        });
    }
    function closeDetails() {
      var area = document.getElementById('pilot-details');
      if (area) area.classList.add('hidden');
    }
    function showPilotDetails() {
      if (!panelPilot) return;
      var title = document.getElementById('details-title');
      var dbody = document.getElementById('details-body');
      var area = document.getElementById('pilot-details');
      if (title) title.textContent = panelPilot.name;
      if (dbody) dbody.innerHTML = 'Loading\u2026';
      if (area) area.classList.remove('hidden');
      area.scrollIntoView({behavior:'smooth', block:'start'});
      var chars = [panelPilot];
      (panelPilot.hasa || []).forEach(function(a) {
        chars.push(a);
      });
      var ids = chars.map(function(c) {
        return c.character_id;
      }).join(',');
      fetch('/monitor/status/pilot-wealth/?app='
            + panelApp + '&ids=' + ids)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (dbody) dbody.innerHTML =
            renderWealthTable(
              panelPilot, data.wealth || {}, data);
        })
        .catch(function() {
          if (dbody) dbody.innerHTML =
            '<p>Details unavailable.</p>';
        });
    }
  </script>"""


def status_view(request: HttpRequest) -> HttpResponse:
    """Render a compact status page for EVE and Mumble connection types."""
    refresh_requested = (
        request.GET.get("refresh", "").strip().lower() in {"1", "true", "yes", "on"}
    )
    if refresh_requested:
        try:
            verify_connections(verbose=False)
        except SystemExit:
            # Keep serving status even when checks fail.
            pass
        refresh_roster_cache()

    status = collect_connection_status()
    checked = bool(status.get("databases"))
    last_check = str(
        status.get("timestamp")
        or datetime.now().isoformat(timespec="seconds")
    )

    database_status: dict[str, dict[str, object]] = {}
    for entry in status.get("databases", []):
        alias = str(entry.get("alias") or "")
        if alias:
            database_status[alias] = entry

    identifier = (
        getattr(settings, "ALLIANCE_ID", None)
        or getattr(settings, "ALLIANCE_TICKER", None)
    )
    alliance_logo_url: str | None = None
    raw_alliance_id = getattr(settings, "ALLIANCE_ID", None)
    if raw_alliance_id is not None:
        first_id = str(raw_alliance_id).split(",")[0].strip()
        try:
            alliance_id_int = int(first_id)
        except (TypeError, ValueError):
            alliance_id_int = None
        if alliance_id_int and alliance_id_int > 0:
            alliance_logo_url = (
                f"https://images.evetech.net/alliances/"
                f"{alliance_id_int}/logo?size=1024"
            )

    rows: list[dict[str, object]] = []
    any_eve_ok = False

    for eve_alias, eve_type in [
        ("default", "CUBE"), ("mysql", "AUTH")
    ]:
        if eve_alias not in settings.DATABASES:
            continue
        eve_config = settings.DATABASES[eve_alias]
        eve_state = database_status.get(
            eve_alias, {"ok": False, "error": "not checked"}
        )
        eve_ok = bool(eve_state.get("ok"))
        any_eve_ok = any_eve_ok or eve_ok
        eve_tooltip = str(eve_state.get("error") or "OK")
        if not checked:
            eve_mains = "-"
            eve_orphans = "-"
            eve_spies = "-"
        elif not eve_ok:
            eve_mains = "(offline)"
            eve_orphans = "(offline)"
            eve_spies = "(offline)"
        else:
            eve_mains = "-"
            eve_orphans = "-"
            eve_spies = "-"
            try:
                roster = get_roster_payload(eve_type)
                if roster.get("ok"):
                    counts = roster.get("counts") or {}
                    eve_mains = str(int(counts.get("main", 0)))
                    eve_orphans = str(int(counts.get("orphan", 0)))
                    eve_spies = str(int(counts.get("spy", 0)))
                else:
                    roster_err = str(roster.get("error") or "cache build failed")
                    eve_tooltip = f"{eve_tooltip} | pilots: {roster_err}"
            except Exception as exc:
                eve_tooltip = f"{eve_tooltip} | pilots: {exc}"
        panel_app: str | None = (
            eve_type
            if eve_mains.isdigit() and int(eve_mains) > 0
            else None
        )
        panel_orphans_app: str | None = (
            eve_type
            if eve_orphans.isdigit() and int(eve_orphans) > 0
            else None
        )
        panel_spies_app: str | None = (
            eve_type
            if eve_spies.isdigit() and int(eve_spies) > 0
            else None
        )
        rows.append(
            {
                "app": "EVE",
                "type": eve_type,
                "host": str(eve_config.get("HOST") or "-"),
                "mains": eve_mains,
                "orphans": eve_orphans,
                "spies": eve_spies,
                "panel_app": panel_app,
                "panel_orphans_app": panel_orphans_app,
                "panel_spies_app": panel_spies_app,
                "last_check": last_check,
                "tooltip": eve_tooltip,
            }
        )

    client_status = status.get("mumble_client") or {}
    mumble_host = str(
        client_status.get("host")
        or getattr(settings, "PYMUMBLE_SERVER", "127.0.0.1")
    )
    client_ok = bool(client_status.get("ok"))
    if client_ok:
        client_tooltip = "OK"
    else:
        client_tooltip = str(client_status.get("error") or "not checked")
    if not checked or client_ok:
        client_mains = "-"
    else:
        client_mains = "(offline)"
    rows.append(
        {
            "app": "Mumble",
            "type": "Client",
            "host": mumble_host,
            "mains": client_mains,
            "orphans": "-",
            "spies": "-",
            "panel_app": None,
            "panel_orphans_app": None,
            "panel_spies_app": None,
            "last_check": last_check,
            "tooltip": client_tooltip,
        }
    )

    mumble_mysql = database_status.get(
        "mumble_mysql", {"ok": False, "error": "not checked"}
    )
    mumble_psql = database_status.get(
        "mumble_psql", {"ok": False, "error": "not checked"}
    )
    raw_ok_aliases: list[str] = []
    if bool(mumble_mysql.get("ok")):
        raw_ok_aliases.append("mumble_mysql")
    if bool(mumble_psql.get("ok")):
        raw_ok_aliases.append("mumble_psql")

    if len(raw_ok_aliases) == 1:
        raw_type = (
            "MYSQL" if raw_ok_aliases[0] == "mumble_mysql" else "PSQL"
        )
    elif len(raw_ok_aliases) == 2:
        raw_type = "MYSQL|PSQL"
    else:
        parts = []
        if "mumble_mysql" in settings.DATABASES:
            parts.append("MYSQL")
        if "mumble_psql" in settings.DATABASES:
            parts.append("PSQL")
        raw_type = "|".join(parts) or "DB"

    raw_tooltip_parts = [
        "MYSQL: "
        + ("OK" if bool(mumble_mysql.get("ok")) else str(mumble_mysql.get("error") or "failed")),
        "PSQL: "
        + ("OK" if bool(mumble_psql.get("ok")) else str(mumble_psql.get("error") or "failed")),
    ]
    raw_mains = "-"
    if raw_ok_aliases:
        try:
            primary_alias = raw_ok_aliases[0]
            with connections[primary_alias].cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM users")
                row = cursor.fetchone()
            if row:
                raw_mains = str(row[0])
        except Exception as exc:
            raw_tooltip_parts.append(f"COUNT: {exc}")
    elif checked:
        raw_mains = "(offline)"
    rows.append(
        {
            "app": "Mumble",
            "type": raw_type,
            "host": str(getattr(settings, "MUMBLE_DB_HOST", "-")),
            "mains": raw_mains,
            "orphans": "-",
            "spies": "-",
            "panel_app": None,
            "panel_orphans_app": None,
            "panel_spies_app": None,
            "last_check": last_check,
            "tooltip": " | ".join(raw_tooltip_parts),
        }
    )

    ice_entries = status.get("ice", [])
    ice_ok = any(bool(entry.get("ok")) for entry in ice_entries)
    ice_host = str(getattr(settings, "ICE_HOST", "127.0.0.1"))
    for entry in ice_entries:
        host_value = entry.get("host")
        if host_value:
            ice_host = str(host_value)
            if bool(entry.get("ok")):
                break
    ice_mains = "-"
    ice_tooltip = "OK"
    if ice_ok:
        try:
            from .services.ice_client import ICEClient, resolve_ice_connections

            ice_connections = resolve_ice_connections()
            selected = next(
                (
                    entry
                    for entry in ice_connections
                    if str(entry.get("HOST") or "") == ice_host
                ),
                ice_connections[0] if ice_connections else {},
            )
            server_id = normalize_server_id(selected.get("SERVER_ID", 1))
            with ICEClient(
                server_id=server_id,
                host=str(selected.get("HOST") or ice_host),
                port=selected.get("PORT"),
                secret=selected.get("SECRET"),
                ini_path=selected.get("INI_PATH"),
            ) as ice:
                ice_mains = str(len(list(ice.get_users())))
        except Exception as exc:
            ice_tooltip = str(exc)
    else:
        ice_mains = "(offline)" if checked else "-"
        errors = [
            str(entry.get("error"))
            for entry in ice_entries
            if entry.get("error")
        ]
        if errors:
            ice_tooltip = " | ".join(errors)
        elif not ice_entries:
            ice_tooltip = "not checked"
    rows.append(
        {
            "app": "Mumble",
            "type": "ICE",
            "host": ice_host,
            "mains": ice_mains,
            "orphans": "-",
            "spies": "-",
            "panel_app": None,
            "panel_orphans_app": None,
            "panel_spies_app": None,
            "panel_ice_users": ice_ok,
            "last_check": last_check,
            "tooltip": ice_tooltip,
        }
    )

    any_ok = any_eve_ok or client_ok or bool(raw_ok_aliases) or ice_ok
    startup_messages = get_last_verify_messages()
    page_title = f"monitor {_monitor_version()}"

    lines: list[str] = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        "  <meta charset=\"utf-8\">",
        f"  <title>{escape(page_title)}</title>",
        "  <style>",
    ]
    if alliance_logo_url:
        lines.extend([
            "    body { font-family: sans-serif; margin: 2rem;",
            "      background-color: #fff;",
            "      background-image: linear-gradient("
            "rgba(255,255,255,.75), rgba(255,255,255,.75)),",
            f"        url('{alliance_logo_url}');",
            "      background-repeat: repeat, no-repeat;",
            "      background-position: 0 0, center center;",
            "      background-size: auto, min(68vmin, 740px);",
            "      background-attachment: scroll, fixed;",
            "    }",
        ])
    else:
        lines.append("    body { font-family: sans-serif; margin: 2rem; }")
    lines.extend([
        "    h1 { margin-bottom: 0.5rem; }",
        "    code { background: #f3f3f3; padding: 0 0.25rem; }",
        "    .hidden { display: none !important; }",
        "    .mains-btn {",
        "      background: none; border: none;",
        "      color: #0070c0; text-decoration: underline;",
        "      cursor: pointer; padding: 0; font-size: inherit;",
        "    }",
        "    #pilot-panel {",
        "      position: fixed; top: 0; right: 0;",
        "      width: 320px; height: 100vh;",
        "      background: #fff;",
        "      border-left: 1px solid #ccc;",
        "      box-shadow: -2px 0 6px rgba(0,0,0,.2);",
        "      display: flex; flex-direction: column;",
        "      z-index: 1000;",
        "    }",
        "  </style>",
        "</head>",
        "<body>",
        "  <h1>monitor</h1>",
        "  <p><button onclick=\"window.location.href="
        "'/monitor/status/?refresh=1'\">Refresh</button></p>",
        "  <div id=\"pilot-panel\" class=\"hidden\">",
        "    <div style=\"padding:.75rem 1rem;"
        " border-bottom:1px solid #ccc;"
        " display:flex; justify-content:space-between;"
        " align-items:center;\">",
        "      <strong id=\"panel-title\">Mains</strong>",
        "      <button id=\"panel-details-btn\""
        " onclick=\"showPilotDetails()\""
        " class=\"hidden\""
        " style=\"margin-right:.25rem\">Details</button>",
        "      <button id=\"panel-back-btn\""
        " onclick=\"panelBack()\">Close</button>",
        "    </div>",
        "    <div id=\"panel-body\""
        " style=\"overflow-y:auto; flex:1; padding:.5rem 1rem;\">",
        "    </div>",
        "  </div>",
        _PANEL_SCRIPT,
    ])
    if not any_ok:
        if checked:
            lines.append("  <p><strong>No connections</strong></p>")
        else:
            lines.append(
                "  <p><strong>Not yet checked"
                " \u2014 click Refresh to verify.</strong></p>"
            )
    if startup_messages:
        lines.append("  <h2>Startup Messages</h2>")
        lines.append("  <pre>")
        for message in startup_messages:
            lines.append(escape(message))
        lines.append("  </pre>")
    lines.extend(
        [
        "  <table border=\"1\" cellspacing=\"0\" cellpadding=\"6\">",
        "    <thead>",
        "      <tr>",
        "        <th>Application</th>",
        "        <th>Type</th>",
        "        <th>Host/IP</th>",
        "        <th>Mains</th>",
        "        <th>Orphans</th>",
        "        <th>Spies</th>",
        "        <th>Last Check</th>",
        "      </tr>",
        "    </thead>",
        "    <tbody>",
        ]
    )
    for row in rows:
        pa = row.get("panel_app")
        if pa:
            mains_cell = (
                f"<button class=\"mains-btn\""
                f" onclick=\"openPanel('{pa}','main')\">"
                f"{row['mains']}</button>"
            )
        elif row.get("panel_ice_users"):
            mains_cell = (
                "<button class=\"mains-btn\" onclick=\"openIceUsers()\">"
                f"{row['mains']}</button>"
            )
        else:
            mains_cell = str(row["mains"])
        poa = row.get("panel_orphans_app")
        if poa:
            orphans_cell = (
                f"<button class=\"mains-btn\""
                f" onclick=\"openPanel('{poa}','orphan')\">"
                f"{row['orphans']}</button>"
            )
        else:
            orphans_cell = str(row["orphans"])
        psa = row.get("panel_spies_app")
        if psa:
            spies_cell = (
                f"<button class=\"mains-btn\""
                f" onclick=\"openPanel('{psa}','spy')\">"
                f"{row['spies']}</button>"
            )
        else:
            spies_cell = str(row["spies"])
        lines.extend(
            [
                "      <tr>",
                f"        <td>{row['app']}</td>",
                f"        <td title=\"{row['tooltip']}\">"
                f"{row['type']}</td>",
                f"        <td>{row['host']}</td>",
                f"        <td>{mains_cell}</td>",
                f"        <td>{orphans_cell}</td>",
                f"        <td>{spies_cell}</td>",
                f"        <td>{row['last_check']}</td>",
                "      </tr>",
            ]
        )
    lines.extend([
        "    </tbody>",
        "  </table>",
        "  <div id=\"pilot-details\" class=\"hidden\""
        " style=\"margin-top:1.5rem\">",
        "    <div style=\"display:flex;"
        "justify-content:flex-start;gap:.5rem;"
        "align-items:center;margin-bottom:.5rem\">",
        "      <strong id=\"details-title\"></strong>",
        "      <button onclick=\"closeDetails()\">Close</button>",
        "    </div>",
        "    <div id=\"details-body\""
        " style=\"overflow-x:auto;padding-right:2rem;"
        "padding-bottom:1rem\"></div>",
        "  </div>",
        "</body>",
        "</html>",
    ])
    return HttpResponse("\n".join(lines))


def status_mains_json(request: HttpRequest) -> JsonResponse:
    """
    Return JSON with mains for the requested app type.
    """
    app = (request.GET.get("app") or "").upper()
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"}, status=400
        )

    identifier = (
        getattr(settings, "ALLIANCE_ID", None)
        or getattr(settings, "ALLIANCE_TICKER", None)
    )
    if identifier is None:
        return JsonResponse(
            {"ok": False, "error": "ALLIANCE_ID or ALLIANCE_TICKER not configured"},
            status=400,
        )

    query = (request.GET.get("q") or "").strip().lower()
    try:
        from .services.env import resolve_database_alias

        alias = resolve_database_alias(env=app)
        repo = get_repository(app, using=alias)
        alliance = repo.resolve_alliance(identifier)
        if alliance is None:
            raise ValueError("Unable to resolve alliance")
        names = [pilot.name for pilot in repo.list_mains(alliance_id=alliance.id)]
        if query:
            names = [name for name in names if query in name.lower()]
        return JsonResponse(
            {"ok": True, "app": app, "count": len(names), "names": names}
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "app": app}, status=500
        )


def status_mains_with_alts_json(
    request: HttpRequest,
) -> JsonResponse:
    """
    Return JSON mains list with nested alts for the requested app.
    """
    app = (request.GET.get("app") or "").upper()
    lite = (request.GET.get("lite") or "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"},
            status=400,
        )

    try:
        roster = get_roster_payload(app)
        if not roster.get("ok"):
            return JsonResponse(
                {"ok": False, "error": roster.get("error"), "app": app},
                status=500,
            )
        mains = sorted(
            [pilot for pilot in roster.get("pilots", []) if pilot.get("isa") == "main"],
            key=lambda pilot: str(pilot.get("name") or "").lower(),
        )
        if lite:
            result = [
                {
                    "name": p.get("name"),
                    "character_id": p.get("character_id"),
                    "alliance_name": p.get("alliance_name") or "",
                    "corporation_name": p.get("corporation_name") or "",
                    "has_alts_count": len(p.get("hasa") or []),
                }
                for p in mains
            ]
        else:
            result = [
                {
                    "name": p.get("name"),
                    "character_id": p.get("character_id"),
                    "alliance_name": p.get("alliance_name") or "",
                    "corporation_name": p.get("corporation_name") or "",
                    "alts": sorted(
                        [
                            {
                                "name": a.get("name"),
                                "character_id": a.get("character_id"),
                            }
                            for a in (p.get("hasa") or [])
                        ],
                        key=lambda a: a["name"].lower(),
                    ),
                }
                for p in mains
            ]
        return JsonResponse(
            {"ok": True, "app": app, "mains": result}
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "app": app},
            status=500,
        )


def status_main_alts_json(request: HttpRequest) -> JsonResponse:
    """Return alts for a single main character_id in the requested app."""
    app = (request.GET.get("app") or "").upper()
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"},
            status=400,
        )
    raw_id = (request.GET.get("id") or "").strip()
    if not raw_id:
        return JsonResponse(
            {"ok": False, "error": "id parameter required"},
            status=400,
        )
    try:
        character_id = int(raw_id)
    except ValueError:
        return JsonResponse(
            {"ok": False, "error": "id must be an integer"},
            status=400,
        )

    roster = get_roster_payload(app)
    if not roster.get("ok"):
        return JsonResponse(
            {"ok": False, "error": roster.get("error"), "app": app},
            status=500,
        )
    for pilot in roster.get("pilots", []):
        if pilot.get("isa") != "main":
            continue
        if int(pilot.get("character_id") or 0) != character_id:
            continue
        alts = sorted(
            [
                {
                    "name": alt.get("name"),
                    "character_id": alt.get("character_id"),
                    "alliance_name": alt.get("alliance_name") or "",
                    "alliance_id": alt.get("alliance_id") or 0,
                    "corporation_name": alt.get("corporation_name") or "",
                }
                for alt in (pilot.get("hasa") or [])
            ],
            key=lambda alt: str(alt.get("name") or "").lower(),
        )
        return JsonResponse(
            {
                "ok": True,
                "app": app,
                "character_id": character_id,
                "alts": alts,
            }
        )
    return JsonResponse(
        {"ok": False, "error": "main not found", "app": app},
        status=404,
    )


def status_pilots_json(request: HttpRequest) -> JsonResponse:
    """
    Return all pilots for the requested app, each tagged with:
    - isa: "main", "spy", or "orphan"
    - hasa: list of alt objects (with alliance/corp fields)
    Single endpoint replacing mains-with-alts, spies, and orphans.
    """
    app = (request.GET.get("app") or "").upper()
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"},
            status=400,
        )

    roster = get_roster_payload(app)
    if not roster.get("ok"):
        return JsonResponse(
            {"ok": False, "error": roster.get("error"), "app": app},
            status=500,
        )
    return JsonResponse(
        {"ok": True, "app": app, "pilots": roster.get("pilots", [])}
    )


def status_spies_json(request: HttpRequest) -> JsonResponse:
    """
    Return JSON spy list (mains outside alliance with in-alliance
    alts) with nested alts for the requested app.
    """
    app = (request.GET.get("app") or "").upper()
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"},
            status=400,
        )

    try:
        roster = get_roster_payload(app)
        if not roster.get("ok"):
            return JsonResponse(
                {"ok": False, "error": roster.get("error"), "app": app},
                status=500,
            )
        spies = sorted(
            [pilot for pilot in roster.get("pilots", []) if pilot.get("isa") == "spy"],
            key=lambda pilot: str(pilot.get("name") or "").lower(),
        )
        result = [
            {
                "name": p.get("name"),
                "character_id": p.get("character_id"),
                "alliance_name": p.get("alliance_name") or "",
                "corporation_name": p.get("corporation_name") or "",
                "alts": sorted(
                    [
                        {
                            "name": a.get("name"),
                            "character_id": a.get("character_id"),
                            "alliance_name": a.get("alliance_name") or "",
                            "alliance_id": a.get("alliance_id") or 0,
                            "corporation_name": (
                                a.get("corporation_name") or ""
                            ),
                        }
                        for a in (p.get("hasa") or [])
                    ],
                    key=lambda a: a["name"].lower(),
                ),
            }
            for p in spies
        ]
        return JsonResponse(
            {"ok": True, "app": app, "spies": result}
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "app": app},
            status=500,
        )


def status_pilot_wealth_json(
    request: HttpRequest,
) -> JsonResponse:
    """
    Return wallet balance, asset item count, and asset ISK valuation per character.

    GET /monitor/status/pilot-wealth/?app=X&ids=id1,id2,...

    ids: comma-separated EVE character_ids.
    Returns {"ok": true, "wealth": {"<character_id>":
        {"assets": N, "assets_isk": N.N, "wallet": N.N}, ...}}
    null values mean no data row found for that character.
    """
    app = (request.GET.get("app") or "").upper()
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"},
            status=400,
        )
    raw_ids = (request.GET.get("ids") or "").strip()
    if not raw_ids:
        return JsonResponse(
            {"ok": False, "error": "ids parameter required"},
            status=400,
        )
    try:
        eve_ids = [
            int(x) for x in raw_ids.split(",") if x.strip()
        ]
    except ValueError:
        return JsonResponse(
            {"ok": False, "error": "ids must be integers"},
            status=400,
        )
    if not eve_ids:
        return JsonResponse({"ok": True, "wealth": {}})

    try:
        from .services.env import get_db_prefix, resolve_database_alias

        alias = resolve_database_alias(env=app)
        wealth: dict[str, dict] = {
            str(eid): {
                "assets": None,
                "assets_isk": None,
                "wallet": None,
                "sp": None,
                "clones": None,
                "contacts": None,
            }
            for eid in eve_ids
        }
        contacts_total = None
        ph = ", ".join(["%s"] * len(eve_ids))
        with connections[alias].cursor() as cursor:
            if app == "CUBE":
                prefix = get_db_prefix("CUBE", using=alias)
                assets_table = f"{prefix}character_assets_summary"
                wallet_table = f"{prefix}wallet_journal_entries"
                skills_table = f"{prefix}character_skills_summary"

                cursor.execute(
                    "SELECT ec.character_id, s.total_items"
                    f" FROM {assets_table} s"
                    " JOIN accounts_evecharacter ec"
                    "   ON ec.id = s.character_id"
                    f" WHERE ec.character_id IN ({ph})",
                    eve_ids,
                )
                for eve_id, total_items in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth:
                        wealth[key]["assets"] = total_items

                # PostgreSQL DISTINCT ON for latest balance.
                cursor.execute(
                    "SELECT DISTINCT ON (wje.character_id)"
                    " ec.character_id, wje.balance"
                    f" FROM {wallet_table} wje"
                    " JOIN accounts_evecharacter ec"
                    "   ON ec.id = wje.character_id"
                    f" WHERE ec.character_id IN ({ph})"
                    " ORDER BY wje.character_id, wje.date DESC",
                    eve_ids,
                )
                for eve_id, balance in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth and balance is not None:
                        wealth[key]["wallet"] = float(balance)

                # CUBE — SP
                cursor.execute(
                    "SELECT ec.character_id, css.total_sp"
                    " FROM accounts_evecharacter ec"
                    " LEFT JOIN"
                    f" {skills_table} css"
                    "   ON css.character_id = ec.id"
                    f" WHERE ec.character_id IN ({ph})",
                    eve_ids,
                )
                for eve_id, total_sp in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth and total_sp is not None:
                        wealth[key]["sp"] = int(total_sp)
            else:
                # AUTH — memberaudit wallet balance table
                cursor.execute(
                    "SELECT ec.character_id, mwb.total"
                    " FROM memberaudit_characterwalletbalance mwb"
                    " JOIN memberaudit_character mc"
                    "   ON mc.id = mwb.character_id"
                    " JOIN eveonline_evecharacter ec"
                    "   ON ec.id = mc.eve_character_id"
                    f" WHERE ec.character_id IN ({ph})",
                    eve_ids,
                )
                for eve_id, total in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth and total is not None:
                        wealth[key]["wallet"] = float(total)
                # AUTH — memberaudit asset item count
                cursor.execute(
                    "SELECT ec.character_id,"
                    " SUM(ca.quantity)"
                    " FROM memberaudit_characterasset ca"
                    " JOIN memberaudit_character mc"
                    "   ON mc.id = ca.character_id"
                    " JOIN eveonline_evecharacter ec"
                    "   ON ec.id = mc.eve_character_id"
                    f" WHERE ec.character_id IN ({ph})"
                    " GROUP BY ec.character_id",
                    eve_ids,
                )
                for eve_id, qty in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth and qty is not None:
                        wealth[key]["assets"] = int(qty)
                # AUTH — SP
                cursor.execute(
                    "SELECT ec.character_id, sp.total"
                    " FROM memberaudit_characterskillpoints sp"
                    " JOIN memberaudit_character mc"
                    "   ON mc.id = sp.character_id"
                    " JOIN eveonline_evecharacter ec"
                    "   ON ec.id = mc.eve_character_id"
                    f" WHERE ec.character_id IN ({ph})",
                    eve_ids,
                )
                for eve_id, total_sp in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth and total_sp is not None:
                        wealth[key]["sp"] = int(total_sp)
                # AUTH — clones
                cursor.execute(
                    "SELECT ec.character_id, COUNT(jc.id)"
                    " FROM eveonline_evecharacter ec"
                    " JOIN memberaudit_character mc"
                    "   ON mc.eve_character_id = ec.id"
                    " LEFT JOIN"
                    " memberaudit_characterjumpclone jc"
                    "   ON jc.character_id = mc.id"
                    f" WHERE ec.character_id IN ({ph})"
                    " GROUP BY ec.character_id",
                    eve_ids,
                )
                for eve_id, cnt in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth:
                        wealth[key]["clones"] = int(cnt)
                # AUTH — contacts per character
                cursor.execute(
                    "SELECT ec.character_id,"
                    " COUNT(DISTINCT cc.eve_entity_id)"
                    " FROM eveonline_evecharacter ec"
                    " JOIN memberaudit_character mc"
                    "   ON mc.eve_character_id = ec.id"
                    " LEFT JOIN"
                    " memberaudit_charactercontact cc"
                    "   ON cc.character_id = mc.id"
                    # Exclude NPC agents (NPC character IDs).
                    "  AND (cc.eve_entity_id < 3000000"
                    "       OR cc.eve_entity_id > 3999999)"
                    f" WHERE ec.character_id IN ({ph})"
                    " GROUP BY ec.character_id",
                    eve_ids,
                )
                for eve_id, cnt in cursor.fetchall():
                    key = str(eve_id)
                    if key in wealth:
                        wealth[key]["contacts"] = int(cnt)
                # AUTH — unique contacts across all chars
                cursor.execute(
                    "SELECT COUNT(DISTINCT cc.eve_entity_id)"
                    " FROM memberaudit_charactercontact cc"
                    " JOIN memberaudit_character mc"
                    "   ON mc.id = cc.character_id"
                    " JOIN eveonline_evecharacter ec"
                    "   ON ec.id = mc.eve_character_id"
                    f" WHERE ec.character_id IN ({ph})"
                    # Exclude NPC agents (NPC character IDs).
                    "   AND (cc.eve_entity_id < 3000000"
                    "        OR cc.eve_entity_id > 3999999)",
                    eve_ids,
                )
                row = cursor.fetchone()
                if row:
                    contacts_total = int(row[0])

        # Asset valuation (preferred Janice, fallback memberaudit/EveUniverse).
        # Uses a local cache backend (JSON by default) to avoid repeat lookups.
        try:
            from .services.item_pricing import build_default_item_pricer

            repo = get_repository(app, using=alias)
            janice_market = getattr(settings, "JANICE_MARKET", None)
            janice_api_key = getattr(settings, "JANICE_API_KEY", None)
            janice_pricing = getattr(settings, "JANICE_PRICING", "sell")
            janice_variant = getattr(settings, "JANICE_VARIANT", "immediate")
            janice_days = getattr(settings, "JANICE_DAYS", "0")
            cache_ttl_seconds = int(
                getattr(settings, "ITEM_PRICE_CACHE_TTL_SECONDS", 3600)
            )
            cache_file = str(
                getattr(
                    settings,
                    "ITEM_PRICE_CACHE_FILE",
                    "/var/tmp/monitor-item-price-cache.json",
                )
            )
            cache_backend_name = str(
                getattr(settings, "ITEM_PRICE_CACHE_BACKEND", "json")
            )

            fallback_alias = alias
            try:
                # memberaudit fallback pricing should use AUTH DB when available.
                fallback_alias = resolve_database_alias(env="AUTH")
            except Exception:
                fallback_alias = alias

            pricer = build_default_item_pricer(
                using=fallback_alias,
                janice_api_key=str(janice_api_key) if janice_api_key else None,
                janice_market=janice_market,
                janice_pricing=str(janice_pricing),
                janice_variant=str(janice_variant),
                janice_days=str(janice_days),
                cache_backend_name=cache_backend_name,
                cache_file=cache_file,
                cache_ttl_seconds=cache_ttl_seconds,
            )

            for eve_id in eve_ids:
                key = str(eve_id)
                basket = repo.get_pilot_asset_basket(int(eve_id))
                if basket is None or not basket.items:
                    continue
                valuation = pricer.price_items(
                    basket.items,
                    market=janice_market,
                )
                if valuation.prices:
                    wealth[key]["assets_isk"] = float(valuation.total_estimated_isk)
        except Exception:
            # Keep non-pricing wealth rows available even if valuation fails.
            pass
        return JsonResponse({
            "ok": True,
            "wealth": wealth,
            "contacts_total": contacts_total,
        })
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "app": app},
            status=500,
        )


def status_orphans_json(request: HttpRequest) -> JsonResponse:
    """
    Return JSON orphan list with alliance/corp for the requested app.
    """
    app = (request.GET.get("app") or "").upper()
    if app not in {"AUTH", "CUBE"}:
        return JsonResponse(
            {"ok": False, "error": "app must be AUTH or CUBE"},
            status=400,
        )

    try:
        roster = get_roster_payload(app)
        if not roster.get("ok"):
            return JsonResponse(
                {"ok": False, "error": roster.get("error"), "app": app},
                status=500,
            )
        orphans = [
            pilot
            for pilot in roster.get("pilots", [])
            if pilot.get("isa") == "orphan"
        ]
        orphans.sort(
            key=lambda p: (
                str(p.get("alliance_name") or "").lower(),
                str(p.get("corporation_name") or "").lower(),
                str(p.get("name") or "").lower(),
            )
        )
        result = [
            {
                "name": p.get("name"),
                "character_id": p.get("character_id"),
                "alliance_name": p.get("alliance_name") or "",
                "corporation_name": p.get("corporation_name") or "",
            }
            for p in orphans
        ]
        return JsonResponse(
            {"ok": True, "app": app, "orphans": result}
        )
    except Exception as exc:
        return JsonResponse(
            {"ok": False, "error": str(exc), "app": app},
            status=500,
        )


def status_ice_users_json(request: HttpRequest) -> JsonResponse:
    """
    Return JSON with all registered ICE users and online/offline state.

    TODO(review): consider introducing a typed OO object (instead of raw dicts)
    if ICE user data needs in-memory correlation/comparison with mains/alts.
    """
    query = (request.GET.get("q") or "").strip().lower()
    host_override = (request.GET.get("host") or "").strip()
    host_used = ""
    original_host = str(getattr(settings, "ICE_HOST", "127.0.0.1"))
    try:
        from .services.ice_client import ICEClient, resolve_ice_connections

        ice_connections = resolve_ice_connections()
        selected = next(
            (
                entry
                for entry in ice_connections
                if str(entry.get("HOST") or "") == host_override
            ),
            ice_connections[0] if ice_connections else {},
        )
        host_used = str(
            selected.get("HOST")
            or host_override
            or getattr(settings, "ICE_HOST", "127.0.0.1")
        )
        server_id = normalize_server_id(selected.get("SERVER_ID", 1))
        with ICEClient(
            server_id=server_id,
            host=host_used,
            port=selected.get("PORT"),
            secret=selected.get("SECRET"),
            ini_path=selected.get("INI_PATH"),
        ) as ice:
            registered = sorted(
                [str(name) for name in ice.get_users()],
                key=lambda n: n.lower(),
            )
            online_rows = ice.get_online_users()
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "error": str(exc),
                "users": [],
                "host": host_override or host_used or original_host or "",
            },
            status=500,
        )

    online_by_name: dict[str, dict[str, str]] = {}
    for row in online_rows:
        name = str(row.get("user") or "")
        if name:
            online_by_name[name.lower()] = {
                "user": name,
                "session": str(row.get("session") or ""),
                "channel_id": str(row.get("channel_id") or ""),
                "roles": str(row.get("roles") or ""),
                "cert_hash": str(row.get("cert_hash") or ""),
            }

    users: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in registered:
        key = name.lower()
        seen.add(key)
        online = online_by_name.get(key)
        row = {
            "status": "+" if online else "-",
            "user": name,
            "session": (online or {}).get("session", ""),
            "channel_id": (online or {}).get("channel_id", ""),
            "roles": (online or {}).get("roles", ""),
            "cert_hash": (online or {}).get("cert_hash", ""),
        }
        users.append(row)

    # Include online users that are not registered.
    for key, online in online_by_name.items():
        if key in seen:
            continue
        users.append(
            {
                "status": "+",
                "user": str(online.get("user") or key),
                "session": str(online.get("session") or ""),
                "channel_id": str(online.get("channel_id") or ""),
                "roles": str(online.get("roles") or ""),
                "cert_hash": str(online.get("cert_hash") or ""),
            }
        )

    if query:
        users = [row for row in users if query in row["user"].lower()]

    def sort_key(row: dict[str, str]):
        status = row.get("status", "-")
        online_sort = 0 if status == "+" else 1
        return (online_sort, row.get("user", "").lower())

    users.sort(key=sort_key)
    return JsonResponse(
        {"ok": True, "count": len(users), "users": users, "host": host_used}
    )
