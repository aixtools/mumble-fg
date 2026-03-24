# `/profile/` Mumble Panel Wireframe

Best-effort markdown sketch of the current FG `/profile/` Mumble panel.

## Single server

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
|------------------------------------------------------------------|
| Username   [ALLY CORP] Pilot Main                               |
| Address    voice.example.org                                     |
| Port       64738                                                 |
| IsAdmin    Yes                                                   |
|                                                                  |
| [Reset Password]                                                 |
| status: Password reset requested <generated-password>            |
|                                                                  |
| [Custom password (min 8)____________________] [Set Password]     |
+------------------------------------------------------------------+
```

## Multiple servers

```text
+------------------------------------------------------------------+
| MUMBLE                                                           |
| Server [ Country 1 v ]                                           |
|------------------------------------------------------------------|
| Username   [ALLY CORP] Pilot Main                               |
| Address    voice-country-1.example.org                           |
| Port       46969                                                 |
|                                                                  |
| [Reset Password]                                                 |
| status: -                                                        |
|                                                                  |
| [Custom password (min 8)____________________] [Set Password]     |
+------------------------------------------------------------------+
```

Notes:

- Panel scope is one pilot identity; when that pilot has registrations on multiple servers, one panel is shown at a time and server selection switches the displayed server panel (`1 pilot -> N servers`).
- Preferred selector field label is `Server`.
- Preferred selector option name is BG server label/name (human-readable), not a raw endpoint string.
- `IsAdmin` is shown only when true.
- If BG is unavailable, address/status show `BG unavailable` and panel actions are disabled.
