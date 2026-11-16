"""
Correct misleading common names on top-rank taxa (phylum, class, order).

The tree labels a node with the first entry of common_names, and that order came
from the bulk import: nothing chose the best name. So Mammalia showed as "Herbivore",
Myxini (hagfish) as "fish" and Strigiformes (owls) as "Goatsuckers", which are nightjars.

CORRECTIONS is a hand-reviewed list, not a rule: it covers wrong names, garbled entries,
names of only part of a group ("Ants" for Hymenoptera) and blank classes that have an
established common name. Plain style differences such
as "Turtle" or lowercase are left alone. Ranks below order were not reviewed.

Old values are appended to the backup file before writing. Idempotent: a second run
finds nothing to do.

Usage:
    python data/fix_common_names.py --dry-run
    python data/fix_common_names.py [--backup FILE]
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app import database

DEFAULT_BACKUP = "E:/AnimalKingdomSystem/common_names_backup.jsonl"


class Fix(NamedTuple):
    rank: str             # names are shared across ranks, so a row of another rank is skipped
    name: str             # goes first, becoming the tree label
    drop: tuple = ()      # names that are wrong for this taxon (any letter case)


CORRECTIONS: dict[str, Fix] = {
    # Wrong: the name belongs to something else
    "Mammalia":       Fix("class", "Mammals", ("Herbivore",)),
    "Myxini":         Fix("class", "Hagfish", ("fish", "fishes")),
    "Strigiformes":   Fix("order", "Owls", ("Goatsuckers",)),
    "Aulopiformes":   Fix("order", "Lizardfishes and allies", ("Salmons",)),
    "Pterobranchia":  Fix("class", "Pterobranchs", ("Sea Angels",)),
    "Annelida":       Fix("phylum", "Annelids", ("European Sea Mouse",)),
    "Bryophyta":      Fix("phylum", "Mosses", ("Hornworts",)),
    "Sirenia":        Fix("order", "Manatees and dugongs", ("Sirens",)),
    "Pelecaniformes": Fix("order", "Pelicans, herons and ibises", ("Boobies, Pelicans, Cormorants",)),
    "Ciconiiformes":  Fix("order", "Storks", ("Flamingos, Herons, Storks",)),
    "Bacilli":        Fix("class", "Bacilli", ("Aerobic Endospore-Forming Bacteria",)),

    # Garbled or misspelt
    "Araneae":        Fix("order", "Spiders", ("Invertebrates (Spiders)",)),
    "Mollusca":       Fix("phylum", "Molluscs", ("Invertebrates (Molluscs)",)),
    "Octopoda":       Fix("order", "Octopuses", ("Kraken Octopods",)),
    "Isopoda":        Fix("order", "Isopods", ("Indet. Woodlouse",)),
    "Ascomycota":     Fix("phylum", "Ascomycetes", ("Asco'S",)),
    "Basidiomycota":  Fix("phylum", "Basidiomycetes", ("Basidio'S",)),
    "Bryopsida":      Fix("class", "Mosses", ("Lower Plants (Mosses)",)),
    "Charales":       Fix("order", "Stoneworts", ("Lower Plants (Stoneworts)",)),
    "Anthocerotophyta": Fix("phylum", "Hornworts", ("A Hornwort",)),
    "Chrysophyceae":  Fix("class", "Golden algae", ("A Chrysophyte",)),
    "Chilopoda":      Fix("class", "Centipedes", ("Centiped", "Centipeds")),
    "Scutigeromorpha": Fix("order", "House centipedes", ("House Centiped",)),
    "Kinorhyncha":    Fix("phylum", "Mud dragons", ("kinorynchs",)),
    "Chytridiomycota": Fix("phylum", "Chytrids", ("Chitridiomycetes",)),
    "Echinodermata":  Fix("phylum", "Echinoderms"),
    "Pleuronectiformes": Fix("order", "Flatfishes", ("Flat Fish",)),

    # Only part of the group, or an obscure name ahead of the usual one
    "Hemichordata":   Fix("phylum", "Hemichordates"),
    "Porifera":       Fix("phylum", "Sponges"),
    "Rhodophyta":     Fix("phylum", "Red algae"),
    "Chlorophyta":    Fix("phylum", "Green algae"),
    "Charophyta":     Fix("phylum", "Charophytes"),
    "Diplopoda":      Fix("class", "Millipedes"),
    "Hydrozoa":       Fix("class", "Hydrozoans"),
    "Scyphozoa":      Fix("class", "Jellyfish"),
    "Echinoidea":     Fix("class", "Sea urchins"),
    "Ophiuroidea":    Fix("class", "Brittle stars"),
    "Hymenoptera":    Fix("order", "Ants, bees and wasps"),
    "Lepidoptera":    Fix("order", "Butterflies and moths"),
    "Odonata":        Fix("order", "Dragonflies and damselflies"),
    "Orthoptera":     Fix("order", "Crickets and grasshoppers"),
    "Neuroptera":     Fix("order", "Lacewings"),
    "Blattodea":      Fix("order", "Cockroaches and termites"),
    "Megaloptera":    Fix("order", "Alderflies and dobsonflies"),
    "Mecoptera":      Fix("order", "Scorpionflies"),
    "Psocodea":       Fix("order", "Barklice, booklice and parasitic lice"),
    "Opiliones":      Fix("order", "Harvestmen"),
    "Decapoda":       Fix("order", "Crabs, lobsters and prawns"),
    "Phyllodocida":   Fix("order", "Scale worms and ragworms"),
    "Anseriformes":   Fix("order", "Ducks, geese and swans"),
    "Apodiformes":    Fix("order", "Swifts and hummingbirds"),
    "Charadriiformes": Fix("order", "Waders, gulls and auks"),
    "Columbiformes":  Fix("order", "Pigeons and doves"),
    "Coraciiformes":  Fix("order", "Kingfishers and allies"),
    "Falconiformes":  Fix("order", "Falcons"),
    "Accipitriformes": Fix("order", "Hawks and eagles"),
    "Gruiformes":     Fix("order", "Cranes and rails"),
    "Bucerotiformes": Fix("order", "Hornbills and hoopoes"),
    "Lagomorpha":     Fix("order", "Rabbits, hares and pikas"),
    "Anura":          Fix("order", "Frogs and toads"),
    "Acipenseriformes": Fix("order", "Sturgeons and paddlefishes"),
    "Clupeiformes":   Fix("order", "Herrings and anchovies"),
    "Esociformes":    Fix("order", "Pikes and mudminnows"),
    "Gasterosteiformes": Fix("order", "Sticklebacks and seamoths"),
    "Osmeriformes":   Fix("order", "Smelts and allies"),
    "Polypteriformes": Fix("order", "Bichirs and reedfish"),
    "Rajiformes":     Fix("order", "Skates and rays"),
    "Tetraodontiformes": Fix("order", "Pufferfishes and allies"),

    # Classes new with Catalogue of Life, blank until now. Names as given by Wikipedia's
    # article on the group, 2026-11-09. Classes with only an anglicised name ("remipedes")
    # or none in everyday use stay blank.
    "Teleostei":      Fix("class", "Teleosts"),
    "Chondrostei":    Fix("class", "Sturgeons and paddlefishes"),
    "Holostei":       Fix("class", "Gars and bowfins"),
    "Cladistii":      Fix("class", "Bichirs and reedfish"),
    "Petromyzonti":   Fix("class", "Lampreys"),
    "Leptocardii":    Fix("class", "Lancelets"),
    "Appendicularia": Fix("class", "Larvaceans"),
    "Thaliacea":      Fix("class", "Salps, pyrosomes and doliolids"),
    "Octocorallia":   Fix("class", "Soft corals"),
    "Diplura":        Fix("class", "Two-pronged bristletails"),
    "Pentastomida":   Fix("class", "Tongue worms"),
    "Branchiura":     Fix("class", "Fish lice"),
    "Gordioida":      Fix("class", "Horsehair worms"),
    "Nectonematoida": Fix("class", "Marine horsehair worms"),
    "Sagittoidea":    Fix("class", "Arrow worms"),
    "Nuda":           Fix("class", "Beroids"),
}


@dataclass
class Result:
    changed: list = field(default_factory=list)   # (name, old list, new list)
    skipped: list = field(default_factory=list)   # no such row at the expected rank


def corrected(names: list[str], fix: Fix) -> list[str]:
    """The fixed name first, then the old names minus wrong ones and copies of the fixed name."""
    remove = {fix.name.lower(), *(d.lower() for d in fix.drop)}
    return [fix.name, *(n for n in names if n.lower() not in remove)]


def apply_fixes(fixes: dict[str, Fix], backup: str | Path, dry_run: bool = False) -> Result:
    result = Result()
    updates, saved = [], []
    conn = database.get_connection()
    try:
        for name, fix in fixes.items():
            row = conn.execute(
                "SELECT taxon_rank, common_names FROM species WHERE scientific_name = ?", (name,)
            ).fetchone()
            if row is None or row["taxon_rank"] != fix.rank:
                result.skipped.append(name)
                continue
            old = database.parse_common_names(row["common_names"])
            new = corrected(old, fix)
            if new == old:
                continue
            result.changed.append((name, old, new))
            updates.append((database.serialize_common_names(new), name))
            saved.append({"scientific_name": name, "common_names": row["common_names"]})

        if dry_run or not updates:
            return result
        with open(backup, "a", encoding="utf-8") as f:
            for entry in saved:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        with conn:
            conn.executemany("UPDATE species SET common_names = ? WHERE scientific_name = ?", updates)
        return result
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    parser.add_argument("--backup", default=DEFAULT_BACKUP, help="file the old values are appended to")
    args = parser.parse_args()

    result = apply_fixes(CORRECTIONS, args.backup, dry_run=args.dry_run)
    for name, old, new in result.changed:
        removed = sorted({n for n in old if n.lower() not in {x.lower() for x in new}})
        print(f"{name}: {old[0] if old else '(none)'!r} -> {new[0]!r}" + (f"  removed {removed}" if removed else ""))
    print(f"{'Would change' if args.dry_run else 'Changed'} {len(result.changed)} of {len(CORRECTIONS)} rows; "
          f"skipped: {result.skipped or 'none'}")


if __name__ == "__main__":
    main()
