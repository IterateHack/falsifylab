# Serial rechallenge protocols in the CAR-T literature (scenario B, PB1)

- **Rule decision supported:** PB1 keeps B5's serial rechallenge at the source paper's in-house SOP, 3:1 effector-to-target with restimulation every 3–4 days.
- **Within the published range:** 3–4 days sits in the modal 2–4 day window (19 of 25 papers), and 3:1 lies inside the 1:10 to 5:1 range the survey calls defensible, though no surveyed paper used exactly 3:1.
- **1:1 is the modal ratio** (8 of 25 papers), but PB1 still requires 3:1: expansion measured at another ratio is not comparable to the source series (PB1's `violation_effect`).

Literature survey run with Paperclip (paperclip.gxl.ai). Tables and citations are as delivered; the search agent's working notes are omitted.

## Protocols extracted (25 papers, line-verified)

| # | Paper | Yr | E:T (at each stimulation) | Interval | Rounds | Target cells |
|---|---|---|---|---|---|---|
| 1 | CD44v6 CAR [1] | 2020 | not stated on line | **7 d** | 3 | IGROV-1 (irradiated) |
| 2 | B7-H3 CAR [2] | 2020 | **1:1** | **3 d** | 3 | SUP-M2 |
| 3 | STAR Protocols chronic stim [3] | 2023 | **1:8** (1:4 or 1:2 for 1st stim) | **every other day** | 13–17 d of co-culture | Nalm6 (BID-KO) |
| 4 | TGFβ–IL-2/15 switch [4] | 2023 | **1:1** | **7 d** | to day 28 | C4-2B (irradiated) |
| 5 | CAR-T<sub>RM</sub> [5] | 2023 | **2:1** | **5 d** | chronic | AsPC-1 (irradiated) |
| 6 | BCMA TurboCAR [6] | 2023 | **10:1** | **2–3 d** | long-term | MM.1S-Luc-GFP |
| 7 | Stressed-target reprogramming [7] | 2023 | **1:3 or 1:2** | 2–5 d (R1), then **3 d** | 3 | SUM149/159, PANC-1, PCI-13 |
| 8 | AZD0754 STEAP2 [8] | 2023 | **0.3:1** | **3–4 d** | continuous | LNCaP |
| 9 | dSHP1/2 [9] | 2023 | **1:1 or 1:4** | **72 h** | serial | GD2⁺ SKOV3 |
| 10 | ESMA CARs [10] | 2024 | **1:2** (S1), **1:4** (S2–3) | **48 h** | 3 | MOLM-13, HL-60 |
| 11 | FOXO1 (Nature) [11] | 2024 | not readable on line | **3 d** (d14/17/20/23) | 4 | Nalm6 |
| 12 | CD33 membrane-proximal [12] | 2024 | **1:2.5 or 1:10** | **7 d** | 21 d | U937-CD33<sup>high</sup> |
| 13 | IL-7 CAR-T [13] | 2024 | not stated on line | **every 2nd day** | repetitive | target cells |
| 14 | Stim-R ROR1 CAR [14] | 2024 | **1:5** (reset each round) | **3–4 d** | until failure | H1975 ROR1⁺ |
| 15 | hYP218 mesothelin [15] | 2024 | **1:1** | **d1, 3, 6** | 3 | HGC27, SW48 |
| 16 | NKG2D/Dap10-12 [16] | 2024 | **1:1** | **3–4 d** | until <60% viability fails | Ren, BxPC3 monolayers |
| 17 | MUC18 CAR [17] | 2025 | 1×10⁵ CAR⁺ : 1×10⁵ A375 | **2 d** | multiple | A375 |
| 18 | A1R CAR [18] | 2025 | not stated on line | **24 h** | over 72 h | E0771-HER2 |
| 19 | B7-H3 ependymoma [19] | 2025 | **2:1** | **7 d** | until loss of killing/expansion | ependymoma cells |
| 20 | Piezo1 CAR [20] | 2025 | **4:1** | **3 d** (replenish) | over 9 d | K562-meso-RFP |
| 21 | CD5-ablated CAR [21] | 2025 | **1:1** | **4 d** | 5 | mitomycin-C-treated targets |
| 22 | DIPG tonic signaling [22] | 2025 | **1:4** | **3 d** | 3 | DIPG13 |
| 23 | CD28 Y218 [23] | 2026 | **5:1** | **48 h**, then d4 | 3 exposures over 7 d | HPAC-WT |
| 24 | Parallel CAR ITAM [24] | 2026 | **1:1** | **72 h** | ≥5 cycles | Raji, Nalm-6 |
| 25 | BACH2 Sleeping Beauty [25] | 2026 | **1:1** | **2 d** (d10/12/14) | 4 | JeKo-1 |

## Distribution

**E:T ratio.** 1:1 is the single most common reset ratio — 8 of 25 papers [2][4][9][15][16][21][24][25]. But it is not a majority: 7 papers deliberately use **target excess** (1:2 to 1:10, including 0.3:1) to force exhaustion [3][7][8][10][12][14][22], and 5 use **effector excess** of 2:1–10:1 [5][6][19][20][23]. Notably, **not one paper used 3:1** — the effector-excess ratios actually in use were 2:1, 4:1, 5:1 and 10:1.

**Interval.** The modal interval is **2–4 days**: 19 of 25 papers restimulate within that window, with 3 days (or 72 h) the single most frequent choice [2][7][9][11][20][22][24]. Weekly restimulation appears in only 4 of 25 [1][4][12][19]. The 1:1-plus-7-day combination specifically occurs in just one paper [4] — ratio and interval are chosen largely independently.

**Rounds.** 3–5 rounds is the dominant design [1][2][7][10][11][15][21][22][23][25]; several groups instead run "until failure," terminating when residual tumour viability exceeds 60% [16][24] or when T cells stop expanding [19].

**Direct answers.** 1:1 every 7 days is **not** common practice — the ratio is common, the interval is not. 3:1 every 3–4 days is **half right**: 3–4 days is squarely the modal interval, but 3:1 does not appear in this literature at all.

## Conclusion

A protocol rule could defensibly require an E:T ratio anywhere in the range **1:10 to 5:1**, with **1:1** as the reasonable default since it is the most frequently used single value, and with target-excess ratios (1:2 to 1:8) explicitly permitted whenever the stated aim is to induce exhaustion rather than to measure killing. The restimulation interval should be constrained to **2–4 days**, which covers 19 of 25 published protocols; a 5–7 day interval should be allowed but flagged as a minority convention used mainly with slow-growing adherent or irradiated targets [1][4][5][12][19]. The rule should additionally require a **minimum of 3 rounds** (and ideally 4–5), and should mandate that the E:T ratio be *reset* at each round rather than left to drift, since papers that do not reset explicitly flag their assays as "non-normalized" and non-comparable on a per-cell basis [14].

--------  
REFERENCES

[1] Porcellini, S. et al. "CAR T Cells Redirected to CD44v6 Control Tumor Growth in Lung and Ovary Adenocarcinoma Bearing Mice." *Frontiers in Immunology* 11, 99 (2020). doi:10.3389/fimmu.2020.00099  
    https://paperclip.gxl.ai/citations/papers/PMC7010926#L49

[2] Zi, Z. et al. "B7-H3 Chimeric Antigen Receptor Redirected T Cells Target Anaplastic Lymphoma Kinase-Positive Anaplastic Large Cell Lymphoma." *Cancers* 12, 3815 (2020). doi:10.3390/cancers12123815  
    https://paperclip.gxl.ai/citations/papers/PMC7766167#L61

[3] Selli, M. E., Landmann, J. H. et al. "Inducing T cell dysfunction by chronic stimulation of CAR-engineered T cells targeting cancer cells in suspension cultures." *STAR Protocols* 4, 101954 (2023). doi:10.1016/j.xpro.2022.101954  
    https://paperclip.gxl.ai/citations/papers/PMC9826863#L79,L95

[4] Beck, C., Casey, N. P., Persiconi, I. et al. "Development of a TGFβ—IL-2/15 Switch Receptor for Use in Adoptive Cell Therapy." *Biomedicines* 11, 459 (2023). doi:10.3390/biomedicines11020459  
    https://paperclip.gxl.ai/citations/papers/PMC9953633#L37

[5] Jung, I.-Y., Noguera-Ortega, E. et al. "Tissue-resident memory CAR T cells with stem-like characteristics display enhanced efficacy against solid and liquid tumors." *Cell Reports Medicine* 4, 101053 (2023). doi:10.1016/j.xcrm.2023.101053  
    https://paperclip.gxl.ai/citations/papers/PMC10313923#L185

[6] Lin, R. J., Sutton, J., Bentley, T. et al. "Constitutive Turbodomains enhance expansion and antitumor activity of CAR-T cells." *Science Advances* 9, eadg8694 (2023). doi:10.1126/sciadv.adg8694  
    https://paperclip.gxl.ai/citations/papers/PMC10403208#L20

[7] Wang, Y., Drum, D. L., Sun, R. et al. "Stressed target cancer cells drive nongenetic reprogramming of CAR T cells and solid tumor microenvironment." *Nature Communications* 14, 5727 (2023). doi:10.1038/s41467-023-41282-x  
    https://paperclip.gxl.ai/citations/papers/PMC10504259#L95

[8] Zanvit, P., van Dyk, D., Fazenbaker, C. et al. "Antitumor activity of AZD0754, a dnTGFβRII-armored, STEAP2-targeted CAR-T cell therapy, in prostate cancer." *Journal of Clinical Investigation* 133, e169655 (2023). doi:10.1172/JCI169655  
    https://paperclip.gxl.ai/citations/papers/PMC10645390#L73

[9] Taylor, J., Bulek, A., Gannon, I. et al. "Exploration of T-cell immune responses by expression of a dominant-negative SHP1 and SHP2." bioRxiv (2023). doi:10.1101/2023.04.26.538403  
    https://paperclip.gxl.ai/citations/papers/bio_3de089686fd0#L43

[10] Ebbinghaus, M., Wittich, K., Bancher, B. et al. "Endogenous Signaling Molecule Activating (ESMA) CARs: A Novel CAR Design." *International Journal of Molecular Sciences* 25, 615 (2024). doi:10.3390/ijms25010615  
    https://paperclip.gxl.ai/citations/papers/PMC10779313#L336

[11] Doan, A. E., Mueller, K. P., Chen, A. Y. et al. "FOXO1 is a master regulator of memory programming in CAR T cells." *Nature* 629, 211–218 (2024). doi:10.1038/s41586-024-07300-8  
    https://paperclip.gxl.ai/citations/papers/PMC11062920#L89

[12] Freeman, R., Shahid, S., Khan, A. G. et al. "Developing a membrane-proximal CD33-targeting CAR T cell." *Journal for ImmunoTherapy of Cancer* 12, e009013 (2024). doi:10.1136/jitc-2024-009013  
    https://paperclip.gxl.ai/citations/papers/PMC11110598#L47

[13] Wu, H., Xu, Z., Qi, M. et al. "Interleukin-7 expression by CAR-T cells improves CAR-T cell survival and efficacy." *Cancer Immunology, Immunotherapy* 73, 191 (2024). doi:10.1007/s00262-024-03756-9  
    https://paperclip.gxl.ai/citations/papers/PMC11297017#L17

[14] Li, A. W., Briones, J. D., Lu, J. et al. "Engineering potent chimeric antigen receptor T cells by programming signaling during T-cell activation." *Scientific Reports* 14, 21331 (2024). doi:10.1038/s41598-024-72392-1  
    https://paperclip.gxl.ai/citations/papers/PMC11392953#L63,L65

[15] Mir, S., Venugopalan, A., Zhang, J. et al. "Persistence of activated anti-mesothelin hYP218 chimeric antigen receptor T cells in the tumour is associated with efficacy in gastric and colorectal carcinomas." *Clinical and Translational Medicine* 14, e70057 (2024). doi:10.1002/ctm2.70057  
    https://paperclip.gxl.ai/citations/papers/PMC11567854#L28

[16] Obajdin, J., Larcombe-Young, D., Glover, M. et al. "Solid tumor immunotherapy using NKG2D-based adaptor CAR T cells." *Cell Reports Medicine* 5, 101827 (2024). doi:10.1016/j.xcrm.2024.101827  
    https://paperclip.gxl.ai/citations/papers/PMC11604534#L316

[17] Zhang, F., Du, H., Liu, K. et al. "MUC18-Directed chimeric antigen receptor T cells for the treatment of mucosal melanoma." *Journal of Translational Medicine* 23, 471 (2025). doi:10.1186/s12967-025-06365-x  
    https://paperclip.gxl.ai/citations/papers/PMC12020318#L68

[18] Sek, K., Chen, A. X. Y., Cole, T. et al. "Tumor site-directed A1R expression enhances CAR T cell function and improves efficacy against solid tumors." *Nature Communications* 16, 6089 (2025). doi:10.1038/s41467-025-59021-9  
    https://paperclip.gxl.ai/citations/papers/PMC12229354#L22

[19] Mehta, S., Ippagunta, S., Varadharajan, S. et al. "B7-H3 CAR T Cells Are Effective against Ependymomas but Limited by Tumor Size and Immune Response." *Clinical Cancer Research* 31, 3418–3432 (2025). doi:10.1158/1078-0432.CCR-24-3083  
    https://paperclip.gxl.ai/citations/papers/PMC12402791#L55

[20] Luu, N., Li, R., Fang, Y. et al. "Piezo1-mediated mechano-energetics regulate CAR T cell function." Research Square (2025). doi:10.21203/rs.3.rs-7776704/v1  
    https://paperclip.gxl.ai/citations/papers/PMC12633482#L65

[21] Wu, J., Cheng, J., Zhu, L. et al. "CD5 ablation enhances persistence and antitumor potency of engineered T cells by mitigating exhaustion and promoting cytotoxicity." *Journal for ImmunoTherapy of Cancer* 13, e012243 (2025). doi:10.1136/jitc-2025-012243  
    https://paperclip.gxl.ai/citations/papers/PMC12666075#L42

[22] Deng, E. B., Zhong, X., Xin, D. et al. "A Tonic Signaling Code Predicts CAR-T Cell Efficacy in Diffuse Midline Glioma." bioRxiv (2025). doi:10.1101/2025.09.29.679095  
    https://paperclip.gxl.ai/citations/papers/bio_41a5df787c74#L113

[23] Martinez-Planes, E., Ramello, M. C., Fontela, M. G. et al. "C-terminus CD28 phosphorylation (Y218) modulates IL-2 secretion and antitumor effect of CAR-T cells." bioRxiv (2026). doi:10.64898/2026.01.28.701378  
    https://paperclip.gxl.ai/citations/papers/PMC12874040#L59

[24] Kausar, F., Davis, C., Larcombe-Young, D. et al. "Optimization of a parallel CAR for B-cell lymphoma via ITAM attenuation and target specificity validation." *Clinical and Experimental Immunology* (2026). doi:10.1093/cei/uxag032  
    https://paperclip.gxl.ai/citations/papers/PMC13242215#L52

[25] Lee, C.-J., Larsson, A. T., Jubenville, T. A. et al. "Sleeping Beauty mutagenesis identifies BACH2 and other regulators of CD8+ T-cell exhaustion, persistence in vivo, and CAR-T cell function under tumor-associated chronic antigen stimulation." *Journal for ImmunoTherapy of Cancer* 14, e013536 (2026). doi:10.1136/jitc-2025-013536  
    https://paperclip.gxl.ai/citations/papers/PMC13374443#L66

---  
References

[1] Simona Porcellini; Claudia Asperti; Stefano Corna; Eleonora Cicoria; Veronica Valtolina; Anna Stornaiuolo; Barbara Valentinis; Claudio Bordignon; Catia Traversari. CAR T Cells Redirected to CD44v6 Control Tumor Growth in Lung and Ovary Adenocarcinoma Bearing Mice. PubMed Central. 2020. https://doi.org/10.3389/fimmu.2020.00099  
[2] Zhenguo Zi; Haihong Zhao; Huanyu Wang; Xiaojing Ma; Fang Wei. B7-H3 Chimeric Antigen Receptor Redirected T Cells Target Anaplastic Lymphoma Kinase-Positive Anaplastic Large Cell Lymphoma. PubMed Central. 2020. https://doi.org/10.3390/cancers12123815  
[3] Mehmet Emrah Selli; Jack H. Landmann; Corvin Arveseth; Nathan Singh. Inducing T cell dysfunction by chronic stimulation of CAR-engineered T cells targeting cancer cells in suspension cultures. PubMed Central. 2023. https://doi.org/10.1016/j.xpro.2022.101954  
[4] Carole Beck; Nicholas Paul Casey; Irene Persiconi; Neda Nejati Moharrami; Adam Sike; Yixin Jin; Jon Amund Kyte. Development of a TGFβ—IL-2/15 Switch Receptor for Use in Adoptive Cell Therapy. PubMed Central. 2023. https://doi.org/10.3390/biomedicines11020459  
[5] In-Young Jung; Estela Noguera-Ortega; Robert Bartoszek; Sierra M. Collins; Erik Williams; Megan Davis; Julie K. Jadlowsky; Gabriela Plesa; Donald L. Siegel; Anne Chew; Bruce L. Levine; Shelley L. Berger; Edmund K. Moon; Steven M. Albelda; Joseph A. Fraietta. Tissue-resident memory CAR T cells with stem-like characteristics display enhanced efficacy against solid and liquid tumors. PubMed Central. 2023. https://doi.org/10.1016/j.xcrm.2023.101053  
[6] Regina J. Lin; Janette Sutton; Trevor Bentley; Diego A. Vargas-Inchaustegui; Duy Nguyen; Hsin-Yuan Cheng; Hayung Yoon; Thomas J. Van Blarcom; Barbra J. Sasu; Siler H. Panowski; Cesar Sommer. Constitutive Turbodomains enhance expansion and antitumor activity of allogeneic BCMA CAR T cells in preclinical models. PubMed Central. 2023. https://doi.org/10.1126/sciadv.adg8694  
[7] Yufeng Wang; David L. Drum; Ruochuan Sun; Yida Zhang; Feng Chen; Fengfei Sun; Emre Dal; Ling Yu; Jingyu Jia; Shahrzad Arya; Lin Jia; Song Fan; Steven J. Isakoff; Allison M. Kehlmann; Gianpietro Dotti; Fubao Liu; Hui Zheng; Cristina R. Ferrone; Alphonse G. Taghian; Albert B. DeLeo; Marco Ventin; Giulia Cattaneo; Yongxiang Li; Youssef Jounaidi; Peigen Huang; Cristina Maccalli; Hanyu Zhang; Cheng Wang; Jibing Yang; Genevieve M. Boland; Ruslan I. Sadreyev; LaiPing Wong; Soldano Ferrone; Xinhui Wang. Stressed target cancer cells drive nongenetic reprogramming of CAR T cells and solid tumor microenvironment. PubMed Central. 2023. https://doi.org/10.1038/s41467-023-41282-x  
[8] Peter Zanvit; Dewald van Dyk; Christine Fazenbaker; Kelly McGlinchey; Weichuan Luo; Jessica M. Pezold; John Meekin; Chien-ying Chang; Rosa A. Carrasco; Shannon Breen; Crystal Sao-Fong Cheung; Ariel Endlich-Frazier; Benjamin Clark; Nina J. Chu; Alessio Vantellini; Philip L. Martin; Clare E. Hoover; Kenesha Riley; Steve M. Sweet; David Chain; Yeoun Jin Kim; Eric Tu; Nathalie Harder; Sandrina Phipps; Melissa Damschroder; Ryan N. Gilbreth; Mark Cobbold; Gordon Moody; Emily E. Bosco. Antitumor activity of AZD0754, a dnTGFβRII-armored, STEAP2-targeted CAR-T cell therapy, in prostate cancer. PubMed Central. 2023. https://doi.org/10.1172/JCI169655  
[9] Julia Taylor, Anna Bulek, Isaac Gannon, Mathew Robson, Evangelia Kokalaki, Thomas Grothier, Callum McKenzie, Mohamed El-Kholy, Maria Stavrou, Charlotte Traynor-White, Wen-Chean Lim, Panagiota Panagiotou, Saket Srivastava, Vania Baldan, James Silibourne, Mathieu Ferrari, Martin Pule *, Simon Thomas. Exploration of T-cell immune responses by expression of a dominant-negative SHP1 and SHP2. bioRxiv [Preprint]. April 2023. https://doi.org/10.1101/2023.04.26.538403  
[10] "Ebbinghaus, M., Wittich, K., Bancher, B. et al. "Endogenous Signaling Molecule Activating (ESMA) CARs: A Novel CAR Design." *International Journal of Molecular …" PubMed Central. /citations/papers/PMC10779313#L336  
[11] Alexander E. Doan; Katherine P. Mueller; Andy Y. Chen; Geoffrey T. Rouin; Yingshi Chen; Bence Daniel; John Lattin; Martina Markovska; Brett Mozarsky; Jose Arias-Umana; Robert Hapke; In-Young Jung; Alice Wang; Peng Xu; Dorota Klysz; Gabrielle Zuern; Malek Bashti; Patrick J. Quinn; Zhuang Miao; Katalin Sandor; Wenxi Zhang; Gregory M. Chen; Faith Ryu; Meghan Logun; Junior Hall; Kai Tan; Stephan A. Grupp; Susan E. McClory; Caleb A. Lareau; Joseph A. Fraietta; Elena Sotillo; Ansuman T. Satpathy; Crystal L. Mackall; Evan W. Weber. FOXO1 is a master regulator of memory programming in CAR T cells. PubMed Central. 2024. https://doi.org/10.1038/s41586-024-07300-8  
[12] Ruby Freeman; Sanam Shahid; Abdul G Khan; Serena C Mathew; Sydney Souness; Erin R Burns; Jasmine S Um; Kento Tanaka; Winson Cai; Sarah Yoo; Andrew Dunbar; Young Park; Devin McAvoy; Kinga K Hosszu; Ross L Levine; Jaap Jan Boelens; Ivo C Lorenz; Renier J Brentjens; Anthony F Daniyan. Developing a membrane-proximal CD33-targeting CAR T cell. PubMed Central. 2024. https://doi.org/10.1136/jitc-2024-009013  
[13] Huantong Wu; Zhuofan Xu; Maoyang Qi; Penghao Liu; Boyan Zhang; Zhenglin Wang; Ge Chen; Xiaohai Liu; Junqi Liu; Wei Wei; Wanru Duan; Zan Chen. Interleukin-7 expression by CAR-T cells improves CAR-T cell survival and efficacy in chordoma. PubMed Central. 2024. https://doi.org/10.1007/s00262-024-03756-9  
[14] Aileen W. Li; Jessica D. Briones; Jia Lu; Quinn Walker; Rowena Martinez; Hajime Hiraragi; Bijan A. Boldajipour; Purnima Sundar; Shobha Potluri; Gary Lee; Omar A. Ali; Alexander S. Cheung. Engineering potent chimeric antigen receptor T cells by programming signaling during T-cell activation. PubMed Central. 2024. https://doi.org/10.1038/s41598-024-72392-1  
[15] Sameer Mir; Abhilash Venugopalan; Jingli Zhang; Nishanth Ulhas Nair; Manjistha Sengupta; Manakamana Khanal; Chaido Stathopoulou; Qun Jiang; Raffit Hassan. Persistence of activated anti‐mesothelin hYP218 chimeric antigen receptor T cells in the tumour is associated with efficacy in gastric and colorectal carcinomas. PubMed Central. 2024. https://doi.org/10.1002/ctm2.70057  
[16] Jana Obajdin; Daniel Larcombe-Young; Maya Glover; Fahima Kausar; Caroline M. Hull; Katie R. Flaherty; Ge Tan; Richard E. Beatson; Phoebe Dunbar; Roberta Mazza; Camilla Bove; Chelsea Taylor; Andrea Bille; Katelyn M. Spillane; Domenico Cozzetto; Alessandra Vigilante; Anna Schurich; David M. Davies; John Maher. Solid tumor immunotherapy using NKG2D-based adaptor CAR T cells. PubMed Central. 2024. https://doi.org/10.1016/j.xcrm.2024.101827  
[17] Fenghao Zhang; Haizhen Du; Kaiping Liu; Qian Guo; Mengmeng Liang; Jing Shi; Shi Feng; Ting He; Xin-an Lu; Yanfang Tang; Lihua Wang; Qiaozhen Li; Xun Meng; Shu-Hui Liu; Yanping Ding; Yan Kong. MUC18-Directed chimeric antigen receptor T cells for the treatment of mucosal melanoma. PubMed Central. 2025. https://doi.org/10.1186/s12967-025-06365-x  
[18] Kevin Sek; Amanda X. Y. Chen; Thomas Cole; Jesse D. Armitage; Junming Tong; Kah Min Yap; Isabelle Munoz; Phoebe A. Dunbar; Shiyi Wu; Marit J. van Elsas; Olivia Hidajat; Christina Scheffler; Lauren Giuffrida; Melissa A. Henderson; Deborah Meyran; Fernando Souza-Fonseca-Guimaraes; Dat Nguyen; Yu-Kuan Huang; Maria N. de Menezes; Emily B. Derrick; Cheok Weng Chan; Kirsten L. Todd; Jack D. Chan; Jasmine Li; Junyun Lai; Emma V. Petley; Sherly Mardiana; Anthony Bosco; Jason Waithman; Ian A. Parish; Christina Mølck; Gregory D. Stewart; Lev Kats; Imran G. House; Phillip K. Darcy; Paul A. Beavis. Tumor site-directed A1R expression enhances CAR T cell function and improves efficacy against solid tumors. PubMed Central. 2025. https://doi.org/10.1038/s41467-025-59021-9  
[19] Sanya Mehta; Siri Ippagunta; Srinidhi Varadharajan; Alisha Kardian; Nic Laboe; Diana Dinh; Amber B. Jones; Michaela M. Meehl; Jorge Ibañez; Erik Emanus; Tram Dao; Meghan B. Ward; Wilda Orisme; Shannon Lange; Deanna Langfitt; Jeffrey Steinberg; Jason Chiang; Peter Vogel; Heather Sheppard; David W. Ellison; Stephen C. Mack; Giedre Krenciute. B7-H3 CAR T Cells Are Effective against Ependymomas but Limited by Tumor Size and Immune Response. PubMed Central. 2025. https://doi.org/10.1158/1078-0432.CCR-24-3083  
[20] Ngoc Luu; Rui Li; Yifei Fang; Huishu Wang; Yujing Song; Ruiqi Chen; Xiangyi Fang; Junru Liao; Tracy Chen; Andre Kelly; Alexander A. Shestov; Katsuo Kurabayashi; Roddy O’Connor; Louis Hodgson; Saba Ghassemi; Weiqiang Chen. Piezo1-mediated mechano-energetics regulate CAR T cell function. PubMed Central. 2025. https://doi.org/10.21203/rs.3.rs-7776704/v1  
[21] Jia Wu; Jiali Cheng; Li Zhu; Qiang Gao; Haolong Lin; Yuhao Zeng; Yong Li; Weini Li; Ning An; Liang Huang; Min Xiao; Dengju Li; Wei Mu. CD5 ablation enhances persistence and antitumor potency of engineered T cells by mitigating exhaustion and promoting cytotoxicity. PubMed Central. 2025. https://doi.org/10.1136/jitc-2025-012243  
[22] Emily B. Deng, Xiaowen Zhong, Dazhuan Xin, Upendra K. Soni, Wenkun Ma, Xiao Huang, Mingjun Cai, Po-Yu Liang, Jun Bai, Qian Qin, Shreya Mishra, Ming Hu, Arman E. Bayat, Jiajie Diao, Mei Xin, Natasha Pillay-Smiley, Trent R. Hummel, Charles B. Stevenson, Jessica B. Foster, Peter de Blank, Scott Raskin, Carl Koschmann, Jose A. Cancelas, Yi Zheng, Q. Richard Lu *. A Tonic Signaling Code Predicts CAR-T Cell Efficacy in Diffuse Midline Glioma. bioRxiv [Preprint]. October 2025. https://doi.org/10.1101/2025.09.29.679095  
[23] Elena Martinez-Planes; Maria Cecilia Ramello; Miguel G. Fontela; Mohammad-Reza Shokri; Lancia Darville; John Koomen; Youngchul Kim; Daniel Abate-Daga. C-terminus CD28 phosphorylation (Y218) modulates IL-2 secretion and antitumor effect of CAR-T cells. PubMed Central. 2026. https://doi.org/10.64898/2026.01.28.701378  
[24] Fahima Kausar; Christopher Davis; Daniel Larcombe-Young; Camilla Bove; Farzin Farzaneh; Charlotte Graham; Reuben Benjamin; David M Davies; John Maher. Optimization of a parallel CAR for B-cell lymphoma via ITAM attenuation and target specificity validation. PubMed Central. 2026. https://doi.org/10.1093/cei/uxag032  
[25] Chang-Jung Lee; Alex T Larsson; Tyler A Jubenville; Wendy A Hudson; Zach J Seeman; Carli Stewart; Alexander K Tsai; Adam Burrack; Brooke L Kimball; Elizabeth L Siegler; Vianca V Vianzon; Erin E Nolan; Yu-Ling Yang; Christopher M Stehn; Daryl M Gohl; Margaret Donovan; Nuri A Temiz; Flavia E Popescu; Søren Warming; Somasekar Seshagiri; Yun You; Jesse D Riordan; Adam Dupuy; Branden Moriarity; Laura Rogers; Ingunn Stromnes; Saad Kenderian; David Largaespada. Sleeping Beauty mutagenesis identifies BACH2 and other regulators of CD8+ T-cell exhaustion, persistence in vivo, and CAR-T cell function under tumor-associated chronic antigen stimulation. PubMed Central. 2026. https://doi.org/10.1136/jitc-2025-013536  
