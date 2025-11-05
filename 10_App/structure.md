# Structure of the application

## Potential Modules

0. Root Module
    - CLI interface
    - orchestrates other modules
    - handles data storage?
        - if this should be a long-running daemon, should store data, e.g., in sqlite to avoid data loss by restarting

1. Network Scan
    - Input: subnets to scan, scanning settings
    - Output: list of detected (host, port) pairs

2. Web enumeration: finding login pages
    - Input: (host, port) pair, enum settings
    - Output: (vhost?, path) identifying potential web page
    - vhost enumeration
    - directory enumeration
        - can we do this smart? only looking for login pages which should be close to top level
        - could use papers on this (I saw something using ML to enumerate more efficiently)
    - needs way to detect (potential) login pages
        - probably just look for "input[type=password]" for now

3. Webapp Fingerprinting / name&version detection
    - Input: (host, port, vhost, path) identifying potential web page
    - Output: (app name?, version?, fingerprint?) identifying web page
    - how does the fingerprinting work?
        - should do research on existing tools
        - are there recent papers for this?
    - name/version extraction using LLM

4. Database Lookup
    - Input: (app name?, version?, fingerprint?)
    - Output: list of (user, password) pairs with descending probability
    - how does the matching work?
        - fingerprints can be compared 1:1 but what about app names and versions?

5. Credential Web search
    - Input: (app name?, version?, fingerprint?)
    - Output: list of (user, password) pairs with descending probability
    - using LLM
        - how to build web search with LLM? are there existing approaches/papers?
        - how can we search GitHub as well (probably not fully indexed by Google?)

6. Credential testing
    - Input: (host, port, vhost, path) and list of (user, password) with descending probability
    - Output: list of working (user, password)
    - how to handle failed login tries that lock the account?
    - do we need LLM for this as well?
    - what about logins that are not simple html forms?

7. Reporting
    - Input: (host, port, vhost, path, user)
    - notify admin per mail/slack/etc.

8. (CVE Lookup)
    - could also do a CVE lookup if time allows

9. (GitHub scanning)
    - could use LLM to scan popular GitHub repos for creds
    - would not be part of main scanner but help to create extensive database to start with


## Notes

- could allow user to hard-code / inject results between steps (e.g, add a known host/port pair before web enum is done)
- settings (i.e., scanning, enum) could be defined in YAML with one section per module
