# SPDX-FileCopyrightText: 2026 Louis Héraut <louis.heraut@inrae.fr>
# SPDX-License-Identifier: GPL-3.0-or-later
"""What the pipeline says while it works.

The rule is that the shape of the text follows the shape of the run: a banner
for a phase that happens once, one line per unit inside a loop, and a summary
computed over a whole phase rather than over a single file. Before that rule, a
full run wrote about ten thousand lines, thirteen percent of them banners
announcing a transition that had already happened sixty-nine times.

Every line is timestamped: a service that runs at night is read afterwards, and
without a clock nothing says which step cost the time.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

from art import tprint


def is_terminal() -> bool:
    """Animated progress only makes sense on a terminal, never in a journal."""
    return sys.stdout.isatty()


def _stamp() -> str:
    return f"{datetime.now():%H:%M:%S}"


def banner(name: str) -> None:
    """L'entête d'une phase, une seule fois par phase."""
    print()
    tprint(name, "small")


def phase(title: str, detail: str = "") -> None:
    print(f"{_stamp()}  {title}" + (f" : {detail}" if detail else ""))


def line(message: str) -> None:
    """Une ligne d'avancement, typiquement une unité traitée dans une boucle."""
    print(f"{_stamp()}  {message}")


def detail(message: str) -> None:
    """Un détail, aligné sous la ligne à laquelle il se rapporte."""
    print(f"          {message}")


def summary(**valeurs) -> None:
    """Le bilan d'une phase, calculé sur l'ensemble et non sur une unité."""
    parts = [f"{cle.replace('_', ' ')} {valeur}" for cle, valeur in valeurs.items()]
    print(f"{_stamp()}  → {', '.join(parts)}")


def humain(octets: float) -> str:
    for unite, seuil in (("Go", 1e9), ("Mo", 1e6), ("ko", 1e3)):
        if octets >= seuil:
            return f"{octets / seuil:.1f} {unite}"
    return f"{octets:.0f} o"


class Chrono:
    """Mesure une durée et la rend lisible, pour dire ce qui a coûté du temps."""

    def __enter__(self):
        self.debut = time.monotonic()
        return self

    def __exit__(self, *_):
        self.duree = time.monotonic() - self.debut

    def __str__(self) -> str:
        duree = time.monotonic() - getattr(self, "debut", time.monotonic())
        duree = getattr(self, "duree", duree)
        if duree >= 3600:
            return f"{int(duree // 3600)} h {int(duree % 3600 // 60):02d}"
        if duree >= 60:
            return f"{int(duree // 60)} min {int(duree % 60):02d}"
        return f"{duree:.1f} s"
