def recognize_intent(user_input):
    """
    简单的意图识别函数
    :param user_input: 用户输入的问题
    :return: 识别出的意图类别
    """
    # 转换为小写以进行不区分大小写的匹配
    input_lower = user_input.lower()
    
    # 问候类意图
    greetings = ['你好', '嗨', '哈喽', '早上好', '下午好', '晚上好']
    for greeting in greetings:
        if greeting in input_lower:
            return 'greeting'
    
    # 天气类意图
    weather_keywords = ['天气', '气温', '温度', '下雨', '晴天', '多云', '刮风']
    for keyword in weather_keywords:
        if keyword in input_lower:
            return 'weather'
    
    # 数据分析类意图
    data_keywords = ['销售', '销售额', '数据', '分析', '报表', '统计', '查询']
    for keyword in data_keywords:
        if keyword in input_lower:
            return 'data_analysis'
    
    # 默认类别
    return 'general_chat'

# 测试函数
def test_intent_recognition():
    test_cases = [
        '你好',
        '今天天气怎么样',
        '销售额是多少'
    ]
    
    for test_case in test_cases:
        intent = recognize_intent(test_case)
        print(f"问题: '{test_case}' -> 意图类别: {intent}")

# 运行测试
if __name__ == "__main__":
    test_intent_recognition()
    print("测试完成")