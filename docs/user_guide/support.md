# Getting Support

Need help with the Cinema 4D Deadline Cloud submitter? This page will guide you through troubleshooting steps and how to get support when you need it.

## Before You Contact Support

Before reaching out for help, try these troubleshooting steps. They often resolve common issues and will help you provide better information if you do need to contact support.

### Troubleshooting Checklist

- **✅ Update to the latest submitter** - We release updates frequently with bug fixes and improvements. Your issue may already be fixed in a newer version. To check if you're running the latest version:
  1. Find your current version: Open Deadline Cloud Monitor, select any submitted job, and look for **"Submitter Integration Version"** in the job properties panel
  2. Compare with the latest release: Visit the [releases page](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/releases) to see the most recent version
  3. If your version is older, update the submitter and test again before reporting the issue

- **✅ Save Cinema 4D Project with Assets** - Enable the **"Save Cinema 4D Project with Assets"** checkbox in the Job-Specific Settings tab of the submitter. This creates a temporary copy of your project with all assets and fixes file paths, helping identify missing files and organizing assets for render farms. [Learn more about this feature](submitter-features.md#job-specific-settings).

- **✅ Try different Cinema 4D versions** - If you're experiencing issues, test with Cinema 4D 2024, 2025, or 2026 to see if the problem is version-specific.

- **✅ Check existing GitHub issues** - Search the [GitHub Issues page](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/issues) to see if someone else has already reported your problem and found a solution.

- **✅ Try a different OS fleet** - Submit your job to both Windows and Linux fleets if available. Windows generally has better support and compatibility for Cinema 4D features.

- **✅ Create a scene project file** - Use Cinema 4D's **File > Save Project with Assets** to create a self-contained project that includes all dependencies. Zip this file for easy sharing with support.

## When to Contact Support

Different types of issues should be directed to different support channels:

### AWS General Support

Contact AWS Support for:
- AWS account issues
- Billing questions
- General AWS service questions
- Deadline Cloud service availability

You can also report Cinema 4D submitter/adaptor issues through AWS Support, but note that these requests may take longer as they need to be routed to the maintainers of this repository. For faster response on Cinema 4D-specific issues, we recommend using GitHub Issues (see below).

[Contact AWS Support](https://aws.amazon.com/contact-us/)

### Cinema 4D Submitter/Adaptor Support

**Use GitHub Issues as your primary channel** for Cinema 4D-specific problems:

- Submitter bugs or crashes
- Adaptor issues
- Rendering failures specific to Cinema 4D
- Feature requests
- Integration problems

[Open a GitHub Issue](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/issues)

## How to Report Issues on GitHub

### Bug Reports

**Before creating a new bug report:**

1. [Search existing bugs](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/issues?q=is%3Aopen+label%3Abug) to see if your problem has already been reported
2. If you find an existing issue that matches your problem:
   - Add a 👍 reaction to help us prioritize
   - Comment with any additional details or reproduction steps you can provide
   - This helps us understand how many users are affected

**If no existing issue matches**, create a new issue with the "bug" label and include:

1. **Clear description** - What happened vs. what you expected
2. **Steps to reproduce** - Detailed steps so others can recreate the issue
3. **Environment details** - See the checklist below
4. **Error messages** - Full error text, not just screenshots
5. **Logs** - Relevant log files (see below for how to gather them)

### Feature Requests

**Before creating a new feature request:**

1. [Search existing enhancements](https://github.com/aws-deadline/deadline-cloud-for-cinema-4d/issues?q=is%3Aopen+label%3Aenhancement) to see if someone has already suggested your idea
2. If you find an existing request that matches:
   - Add a 👍 reaction to show your support
   - Comment with your specific use case - this strengthens the request and helps us understand different needs
   - The more users who express interest, the higher priority it receives

**If no existing request matches**, create a new issue with the "enhancement" label and explain:

1. **What you want** - Clear description of the desired feature
2. **Why you need it** - Use case and benefits
3. **Current workaround** - How you're handling it now (if applicable)

**Note:** Feature requests help us prioritize development, but there's no guarantee of implementation timeline.

## What to Include in Your Support Request

### Required Information Checklist

When contacting support or creating a GitHub issue, always include:

- **Cinema 4D version** - e.g., Cinema 4D 2025.1.0
- **Operating System** - e.g., Windows 11, macOS 14.2
- **Submitter version** - Found in Extensions > AWS Deadline Cloud Submitter > About
- **Renderer** - Standard, Redshift, Arnold, etc.
- **Fleet configuration** - Worker OS (Windows/Linux), memory requirements, disk space, GPU type if using Redshift
- **Error messages** - Complete error text, not paraphrased

### How to Gather Log Files

Logs are essential for diagnosing issues. Here's how to collect them:

#### Enable Detailed Logging

1. In the Cinema 4D submitter, check **"Activate detailed logging"** in Job-Specific Settings
2. Submit your job
3. After the job completes (or fails), retrieve the logs:
   - Open Deadline Cloud Monitor
   - Navigate to your job
   - Right-click on a task → **View logs**
   - Enable **"View logs for all tasks"**
   - Look for the "Shut down DetailedLogging" section
   - Click **"Download logs"** to save the log files locally for sharing with support

### How to Create Scene Project Files

A scene project file packages your Cinema 4D scene with all its assets:

1. **First, remove any confidential assets or data** from your scene before saving
2. In Cinema 4D, go to **File > Save Project with Assets**
3. Choose a destination folder
4. Cinema 4D will copy your scene and all referenced assets to this folder
5. Zip the entire project folder
6. Share the zip file with support

**Important:** Remove confidential assets *before* using "Save Project with Assets" - not after. Removing assets after saving can cause missing file errors that make it harder to diagnose your original issue.

**Tip:** The best way to share a reproducible test case is with a publicly available scene or a simplified scene that demonstrates the issue without confidential material. If you can recreate the problem with non-proprietary assets, this makes it much easier for support to investigate.

---

**Still need help?** Don't hesitate to reach out. The community and support team are here to help you succeed with Deadline Cloud!

[← Back to User Guide](index.md)
