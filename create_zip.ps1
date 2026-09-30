# Create ZIP of the entire project
Compress-Archive `
  -Path "c:\Users\kechaudhari\OneDrive - Stony Brook University\Documents\AP\backend", `
         "c:\Users\kechaudhari\OneDrive - Stony Brook University\Documents\AP\frontend", `
         "c:\Users\kechaudhari\OneDrive - Stony Brook University\Documents\AP\README.md" `
  -DestinationPath "c:\Users\kechaudhari\OneDrive - Stony Brook University\Documents\AP\industrial-diagnostic-ai.zip" `
  -Force

Write-Host "✅ ZIP created at: industrial-diagnostic-ai.zip"
