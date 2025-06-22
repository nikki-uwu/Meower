Import("env")
env.Execute(
    "$PYTHONEXE " +
    env.subst("$PROJECT_PACKAGES_DIR/tool-esptoolpy/esptool.py") +
    " --chip esp32c3 --port " + env.subst("$UPLOAD_PORT") + " erase_flash"
)
