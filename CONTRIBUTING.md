# Contributing

Thanks for your interest in contributing! This document is still being developed (as of July 25, 2025), so rules may evolve.

**Original author**: Gleb Manokhin (nikki)

## Product Under Development

This project is actively being developed. If you notice any patterns, toolkits, or practices that could be improved, please let me know. I'm open to suggestions for:
- Better libraries or frameworks
- More efficient design patterns
- Performance optimizations
- Code structure improvements
- Anything that makes the project better

## How to Contribute

All contributions should be made through pull requests. During the PR review, we'll discuss what was done and I may ask for changes.

### Firmware Development
- Use PlatformIO with ESP32-C3
- Dependencies are managed in `platformio.ini` - use latest versions where possible

### Hardware Development  
- PCB files are in EasyEDA format
- Verify your changes work with the components I'm using
- Document any modifications clearly

### Python Code
- Add clear comments - if unsure/lazy, use AI to help document your code
- Focus on performance optimization:
  - Use best practices for plotting
  - Implement multithreading where applicable
  - Optimize UDP and real-time operations
- Well-formatted, visually aligned code

and feel free to tell me my code is bad.

## License Compatibility

When including third-party code, only use code with these licenses:

**✅ Allowed:**
- MIT
- Apache 2.0
- BSD

**❌ Not allowed:**
- GPL (any version)
- LGPL
- No license
- Non-commercial licenses

This ensures compatibility with our MIT/Apache dual-licensing.

## Bug Fixes

If you find bugs, you can:
- Submit a PR with the fix
- Open an issue
- Contact me directly

## Licensing of Your Contributions

All contributions will be licensed under the same terms as the project:
- Firmware/Software: MIT OR Apache-2.0 
- Hardware: CERN-OHL-P-2.0

By submitting a PR, you agree to license your contributions under these terms.

---

*Note: These contribution guidelines are still evolving. When in doubt, just submit the PR and we'll figure it out together!*
