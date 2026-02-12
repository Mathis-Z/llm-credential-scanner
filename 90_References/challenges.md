# Webenum + Login Panel Detection

- soft 404 detection
    - some apps respond with 200 for everything
    - need to use simhashes
        - simhashes can break if large part of page is boilerplate
    - this breaks if all pages direct to the login page (e.g. 4gaBoards)
        - already check baseline for login page to fix this issue
- weird redirection behavior
    - servers can use http meta tags to redirect instead of http code 3xx => python requests break
    - JS could be used for redirects
    => need to use full browser
- JS-based rendering
    - full page might be rendered client-side (example: 4gaBoards)
    => need to use full browser
        - challenge: how to determine when rendering is finished?
        - can have race conditions
- Multiple valid credentials in online search
    - some apps have different sets of default creds in different deployment modes
    - current cred search aborts on first found creds
    - potential solution: after testing all creds, start cred search for second chance
- login detection
  - baseline approach works well
    - include many attributes (e.g. cookies, password fields, etc.)
  - wait until login is finished (some pages require longer for login to complete)
    - incremental?
- logging is cluttered, many things happen in parallel, hard to see what happens
    - seperated logs (docker and scanner)
    - take screenshots of browser to see why logins work or not (helps a lot for debugging)
    - create a dashboard to see all results in a structured way (e.g. found creds, endpoints, screenshots, etc.)
- pages sometimes contain huge amounts of CSS (style tags), blowing up even 256K context windows
- login can have multiple steps
    - after the first button click, we might need to wait for the next form to appear
    