"""fgbg-common: shared fg/bg eligibility evaluation logic.

This package is duplicated in both mumble-fg and mumble-bg. Both repos
must carry the same version and identical evaluation code so that FG and
BG produce identical eligibility decisions from the same inputs.

Later this will be extracted into a standalone installable package.
"""

VERSION = '0.1.0'
