"""
Android Sync Notice Mutator (scripts/mutators/platforms/android/sync.py)
Injects a self-hosted sync requirement notice and brave://flags instruction into the Android Sync initial setup screen.
"""

from scripts.mutators.context import MutatorContext


def apply(ctx: MutatorContext):
    # Add self-hosted sync notice banner into Android Sync initial layout
    old_android_layout = """            <TextView
               android:layout_width="match_parent"
               android:layout_height="0px"
               android:layout_weight="1.4"
               android:paddingHorizontal="15dip"
               android:text="@string/brave_sync_description_page_1"
               android:gravity="top"
               style="@style/BraveSyncDescriptionTextDefaultRegular" />"""

    new_android_layout = """            <TextView
               android:layout_width="match_parent"
               android:layout_height="0px"
               android:layout_weight="1.4"
               android:paddingHorizontal="15dip"
               android:text="@string/brave_sync_description_page_1"
               android:gravity="top"
               style="@style/BraveSyncDescriptionTextDefaultRegular" />

           <TextView android:id="@+id/cerium_sync_self_host_notice"
               android:layout_width="match_parent"
               android:layout_height="wrap_content"
               android:paddingHorizontal="15dip"
               android:paddingVertical="8dip"
               android:text="Cerium requires a self-hosted sync server (https://github.com/brave/go-sync). Configure the server URL in brave://flags (#brave-override-sync-server-url)."
               android:gravity="center"
               style="@style/BraveSyncDescriptionTextDefaultRegular" />"""

    ctx.replace_in_file(
        "android/java/brave-res/layout/brave_sync_layout.xml",
        old_android_layout,
        new_android_layout,
    )
