# 正则过滤词
import re

QINGLI_AI_BIAOQIAN_ZHUJIE = re.compile(r"<!--.*?-->|<content>|</content>|<summary>.*?</summary>|<thinking>.*?</thinking>|\[1条\]", re.DOTALL)