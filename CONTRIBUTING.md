# CONTRIBUTING.md

## How to Contribute

1. **Fork the repository** and clone your fork locally.
2. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes** – keep the code style consistent with the existing files (Tailwind utility classes, sensible indentation, etc.).
4. **Run the CI locally** (optional but recommended):
   ```bash
   # No build step required for pure HTML, but you can lint the HTML with a tool like htmlhint if you wish.
   ```
5. **Commit and push** your branch:
   ```bash
   git add .
   git commit -m "Describe your change"
   git push origin feature/your-feature-name
   ```
6. **Open a Pull Request** targeting the `main` branch of the upstream repository.
7. Ensure the **GitHub Actions** workflow passes before merging.

## Code of Conduct

Please be respectful and follow the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).
