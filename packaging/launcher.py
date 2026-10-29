import os

if os.environ.get("METALMATE_ROLE") == "overlay":
    from metalmate.overlay_host import host_main  # the background helper that draws the guides

    host_main()
else:
    from metalmate.app import main

    main()
