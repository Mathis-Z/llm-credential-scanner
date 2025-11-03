## Unlocking User‑oriented Pages: Intention‑driven Black‑box Scanner for Real‑world Web Applications (2025)

   * Authors: Weizhe Wang, Yao Zhang, Kaitai Liang, Guangquan Xu, Hongpeng Bai, Qingyang Yan, Xi Zheng, Bin Wu. ([arxiv.org](https://arxiv.org/abs/2504.20801))
   * Focus: A black-box web application scanner called *Hoyen* that uses a large language model to predict user intention and thereby explore deeper user-oriented pages in web apps, expanding the attack surface and finding more vulnerabilities.
   * Relevance: Shows use of AI (LLMs) to guide scanning of web applications.
   * Key result: On 12 open-source web applications it achieved ~2× coverage compared to other scanners and found unique vulnerabilities.
   * Why interesting: Reflects the trend of leveraging AI/LLMs for dynamic scanning and coverage enhancement, beyond simple brute force.

## Offensive AI: Enhancing Directory Brute‑forcing Attack with the Use of Language Models (2024)

   * Authors: Alberto Castagnaro, Mauro Conti, Luca Pajola. ([arxiv.org](https://arxiv.org/abs/2404.14138))
   * Focus: Using language models to enhance directory enumeration (brute forcing directories) across web applications; the AI‐based approach achieved large performance improvements (~969% on average) over traditional wordlist based methods.
   * Relevance: Although more “offensive” in nature, it's relevant to scanning/attack surfaces including web application scanning.
   * Why interesting: Demonstrates how AI can significantly improve scanning/enumeration phases — relevant for both defense (scanner design) and offense.

## Web Application Penetration Testing with Artificial Intelligence: A Systematic Review (2025)

   * Authors: Gustavo Sánchez, Olakunle Olayinka, Aryan Pasikhani. ([publikationen.bibliothek.kit.edu](https://publikationen.bibliothek.kit.edu/1000175432/157334752))
   * Focus: A survey of AI methods tailored to stages of web application penetration testing; examines state of the art, trends, challenges, research gaps.
   * Relevance: Good overview of how AI is being used in the domain of web application scanning/pen testing.
   * Why interesting: Useful for understanding where research is heading, and where gaps (e.g., default credentials scanning, authenticated scanning, network scanning) still remain.

## Securing Modern Web Applications Using AI‑Driven Static and Dynamic Analysis Techniques (2025)

   * Author: Sandeep Phanireddy Sr. ([ijaidsml.org](https://ijaidsml.org/index.php/ijaidsml/article/view/139))
   * Focus: Uses AI in static analysis (source code) and dynamic analysis (runtime) for modern web applications to detect vulnerabilities.
   * Relevance: Although not focused exclusively on “default credentials”, it is a direct application of AI in web application security scanning/analysis.

## Vulnerability Assessment: Analyzing Automated Scanning Techniques for Vulnerability Assessment to Identify Weaknesses and Security Flaws in Network Infrastructure and Systems (2024)

   * Published: July 2024 per the site. ([thesciencebrigade.com](https://thesciencebrigade.com/cndr/article/view/272))
   * Focus: Discusses automated scanning techniques (for networks/infrastructures), their effectiveness, limitations and best practices.
   * Relevance: Although broader than web app scanning, covers scanning of infrastructure, which often overlaps with web app scanning in practice (especially default credentials, network scanning).
   * Why interesting: Helps tie together network scanning and web application scanning; may include default credential aspects implicitly.

## Clinical/standards references:

   * The OWASP Foundation “Testing for Default Credentials” guide (WSTG-ATHN-02) addresses how to test for default/weak credentials in web applications. ([owasp.org](https://owasp.org/www-project-web-security-testing-guide/latest/4-Web_Application_Security_Testing/04-Authentication_Testing/02-Testing_for_Default_Credentials))
   * The vulnerability category for “default credentials / weak credentials” in web applications is documented by Acunetix (web-application scanner) in their vulnerability catalogue. ([Acunetix](https://www.acunetix.com/vulnerabilities/web/web-application-default-weak-credentials/))
   * These show the operational/industry side of default credentials scanning, rather than purely academic.
