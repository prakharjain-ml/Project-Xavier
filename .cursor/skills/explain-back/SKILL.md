---
name: explain-back
description: Teach the human the code just written so they can explain it to a judge. Use after any feature lands in a folder the human owns.
disable-model-invocation: true
---

# Explain back

1. Ask which file or function to explain if it is not obvious from the conversation.
2. Explain it in chunks of 10-20 lines for an advanced-beginner Python programmer: what the chunk does, why it is
   needed, what would break without it. Plain English; define any signal-processing or control term once.
3. Draw the data flow through the function as a short arrow list (input -> steps -> output).
4. Ask the human 2 questions that check real understanding (for example: "What happens if the window is 1 s
   instead of 1.5 s?"). Wait for answers. Correct gently and specifically.
5. Finish with a 2-sentence version the human could say to a judge.
