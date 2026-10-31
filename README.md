# Premium Frontend Demo

This repository contains a **premium, responsive frontend** built with Tailwind CSS and a GitHub Actions workflow that automatically publishes the site to **GitHub Pages**.

## Live Demo
Once the workflow runs, your site will be available at:

```
https://<YOUR_GITHUB_USERNAME>.github.io/<REPOSITORY_NAME>/
```

Replace `<YOUR_GITHUB_USERNAME>` and `<REPOSITORY_NAME>` with your actual GitHub username and repository name.

## Project Structure

```
.
├─ frontend/
│  └─ index.html        # Premium HTML page (Tailwind CSS CDN)
└─ .github/
   └─ workflows/
      └─ gh-pages.yml   # GitHub Actions workflow for deployment
```

## How It Works
1. **Push to `main`** – Whenever you push commits to the `main` branch, the workflow triggers.
2. **GitHub Actions** – The `peaceiris/actions-gh-pages` action builds the site and pushes the contents of the `frontend/` folder to the `gh-pages` branch.
3. **GitHub Pages** – The `gh-pages` branch is served automatically. No manual configuration needed beyond enabling Pages in the repository settings (if you haven't already).

## Setup Instructions
1. **Create a new repository** on GitHub (public or private).
2. Clone the repository locally:
   ```bash
   git clone https://github.com/<YOUR_GITHUB_USERNAME>/<REPOSITORY_NAME>.git
   cd <REPOSITORY_NAME>
   ```
3. Copy the `frontend/` folder and the `.github/` workflow into the repo (the files in this repo).
4. Commit and push:
   ```bash
   git add .
   git commit -m "Add premium frontend and deployment workflow"
   git push origin main
   ```
5. **Enable GitHub Pages** (if not auto‑enabled):
   - Go to *Settings → Pages*.
   - Source: **Deploy from a branch** → `gh-pages` → `/ (root)`.
   - Save.
6. After the Action completes (check the *Actions* tab), visit the URL shown in step 1.

## Customization
- Edit `frontend/index.html` to change content, colors, or layout.
- Use Tailwind utility classes directly – no build step required.
- For more advanced Tailwind configuration, replace the CDN with a local build using `npm` and `postcss`.

## Credits
- **Tailwind CSS** – utility‑first CSS framework (CDN).
- **peaceiris/actions-gh-pages** – GitHub Action for seamless Pages deployment.

---
© 2026 MyProject. All rights reserved.