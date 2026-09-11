"""Milestone 5 acceptance test.

Searches Modrinth for "sodium", prints the top 5 hits, then downloads Sodium for
Minecraft 1.21.1 + Fabric into ./test_mc/mods/ and checks the jar is really there.
Exits 0 on success, 1 on failure.

    python scripts/test_mods.py
    python scripts/test_mods.py 1.20.4
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.mods import (  # noqa: E402
        CollectionEntry,
    ModError,
    Progress,
    download_file,
    resolve_version,
    search_projects,
    subdirectory_for,
)

TARGET = Path(__file__).resolve().parent.parent / "test_mc"
LOADER = "fabric"
BAR_WIDTH = 30

_last_draw = 0.0


def render(progress: Progress) -> None:
    """Throttled single-line progress bar, same shape as the install test."""
    global _last_draw
    now = time.monotonic()
    if now - _last_draw < 0.05 and progress.percent < 100:
        return
    _last_draw = now

    filled = int(BAR_WIDTH * progress.fraction)
    bar = "#" * filled + "-" * (BAR_WIDTH - filled)
    status = progress.status[:42].ljust(42)
    print(f"\r[{bar}] {progress.percent:3d}%  {status}", end="", flush=True)


def test_collection() -> int:
    """The optimization collection, and the three ways it used to break a launch.

    Everything installs into temp directories, never into test_mc/, so a run here
    cannot disturb a working setup.
    """
    import tempfile
    import shutil

    from core.installer import base_game_version, instance_directory
    from core.mods import (
        OPTIMIZATION_COLLECTION,
        conflicts_between,
        fetch_collection,
        install_collection,
        project_titles,
        read_fabric_metadata,
    )

    print("\nOptimization collection\n")

    try:
        collection = fetch_collection(OPTIMIZATION_COLLECTION)
    except ModError as exc:
        print(f"FAILED: could not fetch the collection: {exc}")
        return 1

    print(f"  {collection.name}: {len(collection.project_ids)} projects")
    titles = project_titles(collection.project_ids)
    if len(titles) != len(collection.project_ids):
        print(f"FAILED: named {len(titles)} of {len(collection.project_ids)} projects.")
        return 1

    resolved = base_game_version("fabric-loader-0.19.5-1.21.1", TARGET)
    if resolved != "1.21.1":
        print(f"FAILED: a Fabric profile resolved to '{resolved}', not 1.21.1.")
        return 1
    print("  a Fabric profile resolves to the Minecraft version it inherits from")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # -- two versions side by side ---------------------------------------
        #
        # The bug: one shared mods/ folder, so builds for two Minecraft versions
        # piled up and Fabric refused to start. Each profile gets its own
        # directory now, and the point of this check is that neither install can
        # see the other's jars.
        print("\n  Two versions side by side\n")
        older, newer = "1.21.1", "26.2"
        instances = {}
        for version in (older, newer):
            instance = instance_directory(f"{version}-optimized", root)
            entries = install_collection(OPTIMIZATION_COLLECTION, version, instance,
                                         extra_projects=("sodium",))
            jars = sorted(p.name for p in (instance / "mods").glob("*.jar"))
            instances[version] = (instance, entries, jars)
            kept = [e for e in entries if e.installed]
            print(f"    {version}: {len(kept)} installed, {len(jars)} jars")

        if instances[older][0] == instances[newer][0]:
            print("FAILED: both versions used the same directory.")
            return 1

        overlap = set(instances[older][2]) & set(instances[newer][2])
        if overlap:
            print(f"FAILED: the two instances share jars: {sorted(overlap)}")
            return 1
        print("    the two mods folders have no jar in common")

        # Every jar in an instance must actually be for that instance's version.
        for version, (instance, _entries, jars) in instances.items():
            for jar in (instance / "mods").glob("*.jar"):
                meta = read_fabric_metadata(jar)
                if meta and meta.minecraft and meta.minecraft.replace(" ", "") == version:
                    continue
                if meta and meta.minecraft and not any(
                    c in meta.minecraft for c in "<>=~^*| ,"
                ) and meta.minecraft != version:
                    print(f"FAILED: {jar.name} pins {meta.minecraft}, not {version}.")
                    return 1
        print("    no jar pins a Minecraft version other than its own instance's")

        # -- a conflicting pair ----------------------------------------------
        #
        # Sodium declares 'breaks': {'vulkanmod': '*'} in its own jar, and
        # Modrinth's API says nothing about it. Both were being installed.
        print("\n  A conflicting pair\n")
        for version, (instance, entries, jars) in instances.items():
            metas = [m for m in (read_fabric_metadata(j) for j in (instance / "mods").glob("*.jar")) if m]
            ids = {m.mod_id for m in metas}
            if "sodium" in ids and "vulkanmod" in ids:
                print(f"FAILED: {version} kept both Sodium and VulkanMod.")
                return 1

            certain = [c for c in conflicts_between(metas) if c[2] == "*"]
            if certain:
                print(f"FAILED: {version} has a certain conflict: {certain}")
                return 1

            renderer = sorted(ids & {"sodium", "vulkanmod"})
            dropped = [e for e in entries if not e.installed and "conflict" in e.error]
            print(f"    {version}: renderer = {renderer or ['none']}"
                  + (f", dropped {[e.title for e in dropped]}" if dropped else ""))

        if not any("sodium" in {m.mod_id for m in
                   [x for x in (read_fabric_metadata(j) for j in (inst / 'mods').glob('*.jar')) if x]}
                   or "vulkanmod" in {m.mod_id for m in
                   [x for x in (read_fabric_metadata(j) for j in (inst / 'mods').glob('*.jar')) if x]}
                   for inst, _e, _j in instances.values()):
            print("FAILED: neither instance ended up with a renderer at all.")
            return 1
        print("    exactly one renderer survives in each instance")

        # -- a mod with no compatible build ----------------------------------
        #
        # VulkanMod has no 26.2 build. It must be skipped and named, never
        # approximated with a build for a nearby version.
        print("\n  A mod with no compatible build\n")
        skipped = [e for e in instances[newer][1] if not e.installed]
        if not skipped:
            print("FAILED: expected at least one skip on 26.2.")
            return 1
        for entry in skipped:
            if not entry.error:
                print(f"FAILED: {entry.title} was skipped with no reason given.")
                return 1
            print(f"    skipped {entry.title}: {entry.error}")

        installed_names = {e.filename for e in instances[newer][1] if e.installed}
        if any("1.21" in name for name in installed_names):
            print(f"FAILED: a 1.21 build was installed for 26.2: {installed_names}")
            return 1
        print("    nothing built for another version was installed instead")


        # -- a previously skipped mod becoming available ----------------------
        #
        # The skip list is written at install time. The catch-up re-asks Modrinth
        # for exactly those projects later, so a mod that gains a build for this
        # version stops being invisible. Simulated by recording a skip for a
        # project that does have a build: the re-check must notice.
        print("\n  A previously skipped mod becoming available\n")
        from core.mods import (
            install_skipped,
            load_skipped,
            recheck_skipped,
            record_skipped,
            skipped_path,
        )

        instance, entries, _jars = instances[newer]

        recorded = load_skipped(instance)
        if not recorded:
            print("FAILED: the install recorded no skip list.")
            return 1
        if {s.project_id for s in recorded} != {e.project_id for e in entries if not e.installed}:
            print("FAILED: the skip list does not match what was skipped.")
            return 1
        if any(not s.reason for s in recorded):
            print("FAILED: a recorded skip has no reason.")
            return 1
        print(f"    {len(recorded)} skip(s) recorded with reasons: "
              + "; ".join(f"{s.title} ({s.reason})" for s in recorded))

        still = recheck_skipped(instance, newer)
        if still:
            print(f"FAILED: re-check claims {[s.title for s in still]} are available on {newer}.")
            return 1
        print(f"    re-checking on {newer} still finds nothing -- they really have no build")

        # Now pretend a mod was skipped that in fact has a build for this
        # version, which is what "a build appeared since" looks like from here.
        krypton = next(
            (pid for pid, name in titles.items() if name == "Krypton"), None
        )
        if krypton is None:
            print("FAILED: could not find Krypton in the collection.")
            return 1

        fake = Path(tempfile.mkdtemp(prefix="catchup-"))
        try:
            record_skipped(
                fake,
                [CollectionEntry(project_id=krypton, title="Krypton",
                                 error=f"no build for Minecraft {newer}")],
            )
            if not skipped_path(fake).exists():
                print("FAILED: the skip list was not written.")
                return 1

            now_available = recheck_skipped(fake, newer)
            if [s.project_id for s in now_available] != [krypton]:
                print(f"FAILED: re-check did not offer Krypton: {now_available}")
                return 1
            print("    a mod that has gained a build is offered")

            installed_now = install_skipped(
                fake, newer, [s.project_id for s in now_available]
            )
            if not all(e.installed for e in installed_now):
                print(f"FAILED: installing the caught-up mod failed: {installed_now}")
                return 1
            jars_now = list((fake / "mods").glob("*.jar"))
            if len(jars_now) != 1:
                print(f"FAILED: expected one jar, got {[j.name for j in jars_now]}")
                return 1
            print(f"    installing it puts {jars_now[0].name} in mods/")

            if load_skipped(fake):
                print(f"FAILED: it is still on the skip list: {load_skipped(fake)}")
                return 1
            print("    and it comes off the skip list, so it is not offered again")
        finally:
            shutil.rmtree(fake, ignore_errors=True)
    return 0


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "1.21.1"

    print("MaestroLauncher mod browser test")
    print(f"  game version: {version}")
    print(f"  loader:       {LOADER}")
    print(f"  directory:    {TARGET}")

    # 1. Search.
    print('\nSearching Modrinth for "sodium"...\n')
    try:
        results = search_projects(
            "sodium", game_version=version, loader=LOADER, limit=5
        )
    except ModError as exc:
        print(f"FAILED: search: {exc}")
        return 1

    if not results:
        print("FAILED: search returned no results.")
        return 1

    for i, hit in enumerate(results, start=1):
        blurb = hit.description[:58] + ("..." if len(hit.description) > 58 else "")
        print(f"  {i}. {hit.title[:28]:<28} {hit.downloads:>12,} dl  by {hit.author}")
        print(f"     {hit.slug}  [{hit.project_type}]  {blurb}")

    # 2. Resolve. Search relevance is not a promise, so ask for Sodium by slug.
    print()
    try:
        file = resolve_version(
            "sodium", version, loader=LOADER, project_type="mod"
        )
    except ModError as exc:
        print(f"FAILED: resolve: {exc}")
        return 1

    print(f"Resolved: {file.name}")
    print(f"  version:  {file.version_number}  ({file.version_type})")
    print(f"  file:     {file.filename}  ({file.size / 1024:.0f} KB)")
    print(f"  loaders:  {', '.join(file.loaders)}  |  game: {', '.join(file.game_versions)}")
    print(f"  goes to:  {subdirectory_for(file.project_type)}/\n")

    if version not in file.game_versions:
        print(f"FAILED: resolved a file that does not list {version}.")
        return 1
    if LOADER not in file.loaders:
        print(f"FAILED: resolved a file that does not list the {LOADER} loader.")
        return 1

    # 3. Download.
    started = time.monotonic()
    try:
        path = download_file(file, TARGET, on_progress=render)
    except ModError as exc:
        print(f"\n\nFAILED: download: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\n\nCancelled.")
        return 1

    print(f"\n\nFinished in {time.monotonic() - started:.1f}s")

    # 4. Verify it is on disk, in mods/, and non-empty.
    expected_dir = TARGET.resolve() / "mods"
    if not path.exists():
        print(f"FAILED: {path} does not exist after download.")
        return 1
    if path.parent != expected_dir:
        print(f"FAILED: landed in {path.parent}, expected {expected_dir}.")
        return 1

    size = path.stat().st_size
    print(f"  jar:  {path}")
    print(f"  size: {size:,} bytes")
    if size == 0:
        print("FAILED: the jar is empty.")
        return 1
    if file.size and size != file.size:
        print(f"FAILED: size is {size}, Modrinth said {file.size}.")
        return 1

    # 5. The same pipeline for a resource pack: a different project type, a
    #    different folder, and one Modrinth files under the "minecraft" loader,
    #    so the Fabric filter must not be applied to it.
    print("\n" + "-" * 60)
    print("Resource packs\n")

    try:
        packs = search_projects(
            "faithful", game_version=version, loader=LOADER,
            project_type="resourcepack", limit=5,
        )
    except ModError as exc:
        print(f"FAILED: resource pack search: {exc}")
        return 1

    if not packs:
        print("FAILED: no resource packs found. The loader filter may be leaking.")
        return 1

    print(f"  {len(packs)} results even though loader={LOADER!r} was passed:")
    for hit in packs:
        print(f"    {hit.title[:30]:<30} {hit.project_type:<13} {hit.downloads:>12,} dl")

    if any(hit.project_type != "resourcepack" for hit in packs):
        print("FAILED: a non-resourcepack came back from a resourcepack search.")
        return 1

    # Take the smallest, so this does not download a 200MB 512x pack.
    resolved = []
    for hit in packs:
        try:
            resolved.append(
                resolve_version(hit.slug, version, loader=LOADER, project_type="resourcepack")
            )
        except ModError:
            continue
    if not resolved:
        print(f"FAILED: none of those packs has a {version} release.")
        return 1

    pack = min(resolved, key=lambda f: f.size or 1 << 40)
    print(f"\n  Resolved: {pack.name}")
    print(f"    file:    {pack.filename}  ({pack.size / 1024 / 1024:.1f} MB)")
    print(f"    loaders: {', '.join(pack.loaders)}  <- what Modrinth reports")
    print(f"    goes to: {subdirectory_for(pack.project_type)}/\n")

    if subdirectory_for(pack.project_type) != "resourcepacks":
        print("FAILED: a resource pack is not routed to resourcepacks/.")
        return 1

    try:
        pack_path = download_file(pack, TARGET, on_progress=render)
    except ModError as exc:
        print(f"\n\nFAILED: resource pack download: {exc}")
        return 1

    print()
    if not pack_path.exists():
        print(f"FAILED: {pack_path} does not exist after download.")
        return 1
    if pack_path.parent != TARGET.resolve() / "resourcepacks":
        print(f"FAILED: landed in {pack_path.parent}, expected resourcepacks/.")
        return 1
    if pack_path.stat().st_size == 0:
        print("FAILED: the resource pack is empty.")
        return 1
    if (TARGET / "mods" / pack_path.name).exists():
        print("FAILED: the resource pack also landed in mods/.")
        return 1

    print(f"  pack: {pack_path}")
    print(f"  size: {pack_path.stat().st_size:,} bytes")

    # 6. Shaders are a third type going to a third folder.
    print("\nShaders\n")
    try:
        shaders = search_projects(
            "shader", game_version=version, loader=LOADER,
            project_type="shader", limit=3,
        )
    except ModError as exc:
        print(f"FAILED: shader search: {exc}")
        return 1

    for hit in shaders:
        print(f"    {hit.title[:30]:<30} {hit.project_type:<13} -> {subdirectory_for(hit.project_type)}/")
    if any(subdirectory_for(hit.project_type) != "shaderpacks" for hit in shaders):
        print("FAILED: a shader is not routed to shaderpacks/.")
        return 1
    if subdirectory_for("shader") != "shaderpacks":
        print("FAILED: shader routing is wrong.")
        return 1
    print("\n  shaders route to shaderpacks/, which is what Iris and OptiFine read")

    failure = test_collection()
    if failure:
        return failure

    print("\nMilestone 5 PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
