# Hardware

Laptop, CPU only, 16 GB RAM

# Models

## qwen3:8b-q4_K_M

```
1
MIND
```
total duration:       53.693010252s
load duration:        77.279128ms
prompt eval count:    740 token(s)
prompt eval duration: 52.964309187s
prompt eval rate:     13.97 tokens/s
eval count:           5 token(s)
eval duration:        633.555408ms
eval rate:            7.89 tokens/s


## qwen3:4b-instruct-2507-q4_K_M

```
2
MIND login page
MIND default credentials
```
total duration:       30.945663824s
load duration:        83.574303ms
prompt eval count:    732 token(s)
prompt eval duration: 29.762116591s
prompt eval rate:     24.60 tokens/s
eval count:           12 token(s)
eval duration:        1.07903744s
eval rate:            11.12 tokens/s

Note: I think we might use this model for tasks that don't require (or benefit from) a thinking section. In this case the speedup might be worth it but otherwise the 8B model in thinking mode seems to be more practical.

## qwen3:4b-thinking-2507-q4_K_M 
```
2
MIND
MIND login
```
total duration:       11m3.866111955s
load duration:        83.549485ms
prompt eval count:    734 token(s)
prompt eval duration: 30.284027511s
prompt eval rate:     24.24 tokens/s
eval count:           3891 token(s)
eval duration:        10m31.552112491s
eval rate:            6.16 tokens/s

Note: The model produces an outrageously large thinking section repeating itself constantly. Thats why it performs so poorly. I think this model is primarily for getting the most out of minimal hardware (<8 GB VRAM) if time does not matter.
