# Research behind the design

[Documentation index](README.md) · [Architecture](architecture.md) · [Benchmarking](benchmarking.md)

These papers explain relevant ideas; their results are not accuracy or latency claims for IntentBench:

- **Sentence-BERT — Reimers and Gurevych (2019):** introduces sentence embeddings suitable for semantic similarity with cosine comparison. It provides background for embedding retrieval, without implying that every configured model uses SBERT or performs equally on intent catalogs. [Paper](https://aclanthology.org/D19-1410/)
- **Reciprocal Rank Fusion — Cormack, Clarke, and Buettcher (2009):** combines ranked retrieval lists using reciprocal ranks. Its TREC/LETOR experiments motivate rank aggregation; gains in those settings do not guarantee gains for this project's lexical/dense intent fusion. [Paper](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf)
- **Retrieval-Augmented Generation — Lewis et al. (2020):** combines neural retrieval and generation for knowledge-intensive language tasks. It offers a conceptual connection to conditioning a model on retrieved evidence. IntentBench selects intents; it does not implement the paper's trained RAG architecture or question-answering system. [Paper](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)
- **An Evaluation Dataset for Intent Classification and Out-of-Scope Prediction — Larson et al. (2019):** evaluates 150 intents across ten domains and highlights the difficulty of OOS detection despite strong in-scope classification. This motivates separate rejection metrics; CLINC150 is not the bundled dataset. [Paper](https://aclanthology.org/D19-1131/)
- **Lost in the Middle — Liu et al. (2024):** finds sensitivity to information position in long contexts on question-answering and key-value retrieval tasks. This motivates testing shortlist size and presentation; it does not establish an optimal candidate count for intent routing. [Paper](https://aclanthology.org/2024.tacl-1.9/)
