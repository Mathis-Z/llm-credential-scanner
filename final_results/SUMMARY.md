# Aggregated results: 10 runs per (backend, network) = 5 VMs x run-01/run-02
# Generated from final_results/vmX/{local,remote}/{test-network,evaluation-network}/run-0{1,2}/output.log

## Backend: remote — GPT-4o mini (remote API)

### test-network (17 apps)
  Found     : majority-pass(>=6/10)=15/17  any-pass(>=1/10)=16/17
  Verified  : majority-pass(>=6/10)=14/17  any-pass(>=1/10)=16/17
  NoInvalid : majority-pass(>=6/10)=16/17  any-pass(>=1/10)=16/17
  LoginPanel: majority-pass(>=6/10)=16/17  any-pass(>=1/10)=16/17
  avg tokens/app: in=102211 out=744  avg time/app: 203.0s
  avg est. cost/app (GPT 4o mini, $0.15/$0.60 per M in/out tok): $0.0158

  Per-app P/F/U (out of 10) — Found/Verified/NoInvalid/LoginPanel — avg in/out tokens:
    4gaBoards        1P/9F/0U      1P/9F/0U      10P/0F/0U     10P/0F/0U     in=23054 out=622
    BabyBuddy        10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=58268 out=604
    BookStack        10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=363183 out=980
    CalibrWeb        8P/2F/0U      8P/2F/0U      10P/0F/0U     10P/0F/0U     in=80511 out=1586
    ClipCascade      10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=46856 out=721
    Convertigo       0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    DockerSSOServer  10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=135976 out=708
    Filadex          10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=17252 out=437
    Grafana          10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=86693 out=388
    Joplin           10P/0F/0U     9P/1F/0U      10P/0F/0U     10P/0F/0U     in=29056 out=648
    osTicket         8P/2F/0U      8P/2F/0U      10P/0F/0U     10P/0F/0U     in=228838 out=1958
    ownCloud         10P/0F/0U*    7P/3F/0U      10P/0F/0U     10P/0F/0U     in=221126 out=494
    PasswordCockpit  10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=66631 out=744
    Pyload           8P/0F/2U*     4P/4F/2U      8P/0F/2U      8P/0F/2U      in=138801 out=1007
    Readmine         10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=56396 out=610
    SonarQube        10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=57877 out=452
    Zabbix           10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=127068 out=687


### evaluation-network (27 apps)
  Found     : majority-pass(>=6/10)=20/27  any-pass(>=1/10)=21/27
  Verified  : majority-pass(>=6/10)=14/27  any-pass(>=1/10)=18/27
  NoInvalid : majority-pass(>=6/10)=20/27  any-pass(>=1/10)=23/27
  LoginPanel: majority-pass(>=6/10)=23/27  any-pass(>=1/10)=23/27
  avg tokens/app: in=59891 out=613  avg time/app: 201.7s
  avg est. cost/app (GPT 4o mini, $0.15/$0.60 per M in/out tok): $0.0094

  Per-app P/F/U (out of 10) — Found/Verified/NoInvalid/LoginPanel — avg in/out tokens:
    ActiveMQ                0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    Airsonic                10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=25788 out=724
    ApacheGuacamole         0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    Cacti                   10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=20524 out=316
    Casdoor                 0P/10F/0U     0P/10F/0U     4P/6F/0U      10P/0F/0U     in=93693 out=1032
    EMQXDashboard           10P/0F/0U     9P/1F/0U      10P/0F/0U     10P/0F/0U     in=162423 out=916
    EventStoreDB            0P/10F/0U     0P/10F/0U     10P/0F/0U     10P/0F/0U     in=23120 out=567
    Filebrowser             10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=35123 out=479
    Huginn                  10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=64740 out=923
    Kanboard                10P/0F/0U*    5P/5F/0U      10P/0F/0U     10P/0F/0U     in=40647 out=750
    Keycloak                10P/0F/0U*    0P/10F/0U     10P/0F/0U     10P/0F/0U     in=23433 out=801
    KibanaOSS               10P/0F/0U     8P/2F/0U      10P/0F/0U     10P/0F/0U     in=54520 out=857
    MinIO                   10P/0F/0U     7P/3F/0U      10P/0F/0U     10P/0F/0U     in=208785 out=836
    NexusRepositoryManager  0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    NginxProxyManager       10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=46706 out=716
    NuxeoServer             10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=30398 out=733
    OpenSearchDashboards    10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=19313 out=552
    OpenVAS                 0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    RabbitMQManagement      10P/0F/0U     9P/1F/0U      10P/0F/0U     10P/0F/0U     in=64195 out=991
    Redmine                 10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=47538 out=645
    Rundeck                 10P/0F/0U*    1P/9F/0U      5P/5F/0U      10P/0F/0U     in=61894 out=691
    Seafile                 3P/7F/0U      3P/7F/0U      10P/0F/0U     10P/0F/0U     in=114443 out=889
    StirlingPDF             9P/1F/0U      2P/8F/0U      4P/6F/0U      10P/0F/0U     in=60185 out=479
    Superset                10P/0F/0U*    0P/10F/0U     10P/0F/0U     10P/0F/0U     in=163016 out=458
    Umami                   10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=64842 out=806
    Yacht                   6P/4F/0U      6P/4F/0U      10P/0F/0U     10P/0F/0U     in=174966 out=835
    qBittorrent             10P/0F/0U     0P/10F/0U     10P/0F/0U     10P/0F/0U     in=16770 out=561


## Backend: local — qwen3:4b-instruct-2507-q4_K_M (local, Ollama)

### test-network (17 apps)
  Found     : majority-pass(>=6/10)=14/17  any-pass(>=1/10)=16/17
  Verified  : majority-pass(>=6/10)= 9/17  any-pass(>=1/10)=13/17
  NoInvalid : majority-pass(>=6/10)=16/17  any-pass(>=1/10)=16/17
  LoginPanel: majority-pass(>=6/10)=16/17  any-pass(>=1/10)=16/17
  avg tokens/app: in=41671 out=2723  avg time/app: 248.4s

  Per-app P/F/U (out of 10) — Found/Verified/NoInvalid/LoginPanel — avg in/out tokens:
    4gaBoards        2P/8F/0U      2P/8F/0U      10P/0F/0U     10P/0F/0U     in=26660 out=777
    BabyBuddy        10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=19147 out=390
    BookStack        10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=40625 out=598
    CalibrWeb        5P/5F/0U      2P/8F/0U      10P/0F/0U     10P/0F/0U     in=38988 out=2098
    ClipCascade      10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=21988 out=767
    Convertigo       0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    DockerSSOServer  10P/0F/0U*    0P/10F/0U     9P/1F/0U      10P/0F/0U     in=54188 out=33789
    Filadex          10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=22088 out=607
    Grafana          10P/0F/0U*    5P/5F/0U      9P/1F/0U      10P/0F/0U     in=25242 out=512
    Joplin           10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=24365 out=651
    osTicket         6P/4F/0U      6P/4F/0U      10P/0F/0U     10P/0F/0U     in=199980 out=2802
    ownCloud         10P/0F/0U*    0P/10F/0U     10P/0F/0U     10P/0F/0U     in=39438 out=541
    PasswordCockpit  9P/1F/0U      9P/1F/0U      10P/0F/0U     10P/0F/0U     in=83828 out=854
    Pyload           8P/0F/2U*     5P/3F/2U      8P/0F/2U      8P/0F/2U      in=35250 out=636
    Readmine         10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=23792 out=374
    SonarQube        10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=30442 out=354
    Zabbix           10P/0F/0U     0P/10F/0U     10P/0F/0U     10P/0F/0U     in=22384 out=546


### evaluation-network (27 apps)
  Found     : majority-pass(>=6/10)=19/27  any-pass(>=1/10)=21/27
  Verified  : majority-pass(>=6/10)=14/27  any-pass(>=1/10)=16/27
  NoInvalid : majority-pass(>=6/10)=22/27  any-pass(>=1/10)=23/27
  LoginPanel: majority-pass(>=6/10)=23/27  any-pass(>=1/10)=23/27
  avg tokens/app: in=32318 out=1186  avg time/app: 202.7s

  Per-app P/F/U (out of 10) — Found/Verified/NoInvalid/LoginPanel — avg in/out tokens:
    ActiveMQ                0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    Airsonic                10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=11722 out=437
    ApacheGuacamole         0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    Cacti                   10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=20701 out=359
    Casdoor                 0P/10F/0U     0P/10F/0U     3P/7F/0U      10P/0F/0U     in=117769 out=1162
    EMQXDashboard           10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=121976 out=700
    EventStoreDB            0P/10F/0U     0P/10F/0U     9P/1F/0U      10P/0F/0U     in=21746 out=963
    Filebrowser             10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=15530 out=376
    Huginn                  10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=32742 out=610
    Kanboard                10P/0F/0U*    6P/4F/0U      10P/0F/0U     10P/0F/0U     in=21916 out=605
    Keycloak                10P/0F/0U*    0P/10F/0U     10P/0F/0U     10P/0F/0U     in=26970 out=1049
    KibanaOSS               9P/1F/0U      9P/1F/0U      10P/0F/0U     10P/0F/0U     in=40885 out=1063
    MinIO                   10P/0F/0U     0P/10F/0U     10P/0F/0U     10P/0F/0U     in=35308 out=608
    NexusRepositoryManager  0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    NginxProxyManager       10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=22133 out=639
    NuxeoServer             10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=17866 out=646
    OpenSearchDashboards    10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=20074 out=680
    OpenVAS                 0P/0F/10U     0P/0F/10U     0P/0F/10U     0P/0F/10U     in=0 out=0
    RabbitMQManagement      10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=24905 out=862
    Redmine                 10P/0F/0U*    10P/0F/0U     10P/0F/0U     10P/0F/0U     in=21911 out=504
    Rundeck                 10P/0F/0U*    2P/8F/0U      10P/0F/0U     10P/0F/0U     in=16795 out=488
    Seafile                 1P/9F/0U      1P/9F/0U      10P/0F/0U     10P/0F/0U     in=58466 out=912
    StirlingPDF             10P/0F/0U     8P/2F/0U      10P/0F/0U     10P/0F/0U     in=84246 out=692
    Superset                10P/0F/0U*    0P/10F/0U     10P/0F/0U     10P/0F/0U     in=68980 out=502
    Umami                   10P/0F/0U     10P/0F/0U     10P/0F/0U     10P/0F/0U     in=28418 out=617
    Yacht                   3P/7F/0U      0P/10F/0U     10P/0F/0U     10P/0F/0U     in=27317 out=16988
    qBittorrent             8P/2F/0U      0P/10F/0U     10P/0F/0U     10P/0F/0U     in=14219 out=574


# Notes
- P=PASS, F=FAIL, U=unknown/inconclusive (no login panel found or service not testable, e.g. Docker Compose timeout/boot failure)
- * = found credentials are part of a default-credential wordlist, so a PASS here is not fully indicative of genuine LLM-driven retrieval
- 'majority-pass' = app counted as passing if >=6 of the 10 runs report PASS for that check; used for headline counts in the paper
- Local-backend runs (all 5 VMs) shared a single NVIDIA RTX 5090 GPU running 5 concurrent scans; reported local runtimes reflect this shared-GPU contention
- Remote-backend cost estimate uses $0.15 / $0.60 per 1M input/output tokens (GPT-4o mini pricing used for this evaluation)
- run-03 (present only for some remote evaluation-network/test-network directories) was excluded; only run-01 and run-02 per VM are used, for 5*2=10 runs total

## Actual scanner runtime (excludes Docker Compose startup/teardown)
# Measured from 'Starting scanner' (DEBUG) to 'All modules completed.' (INFO) log timestamps per app-run.
# Apps whose login panel never came up within the startup timeout never invoke the scanner and are excluded (n/a).
remote  test-network         n_runs= 160 avg= 157.8s min=  18.0s max=  364.5s (apps with scanner runs: 16/17)
remote  evaluation-network   n_runs= 240 avg= 143.9s min=  12.0s max=  489.2s (apps with scanner runs: 24/27)
local   test-network         n_runs= 160 avg= 206.3s min=  16.0s max= 1062.5s (apps with scanner runs: 16/17)
local   evaluation-network   n_runs= 240 avg= 149.1s min=  12.0s max= 1012.2s (apps with scanner runs: 24/27)
