# Webenum + Login Panel Detection

- soft 404 detection
    - some apps respond with 200 for everything
    - need to use simhashes
        - simhashes can break if large part of page is boilerplate
- weird redirection behavior
    - servers can use http meta tags to redirect instead of http code 3xx => python requests break
    - JS could be used for redirects
    => need to use full browser
- JS-based rendering
    - full page might be rendered client-side (example: 4gaBoards)
    => need to use full browser
        - challenge: how to determine when rendering is finished?
        - can have race conditions
