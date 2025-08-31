#!/usr/bin/env python3
"""
CodeBench PyTest - Tests correct solutions against all problems
Run with: pytest codebench_pytest.py -v
"""

import pytest
import yaml
import json
import os
import sys
import requests
from typing import Dict, Any, List

# Import the codebench module to use its test runner functions
# Assuming the main file is named 'codebench.py' or similar
try:
    # Try to import the test runner functions from the main app
    from codebench import run_python_test, run_java_test, compare_outputs
except ImportError:
    # If direct import fails, try adding parent directory to path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from codebench import run_python_test, run_java_test, compare_outputs
    except ImportError:
        print("ERROR: Cannot import test runner functions from codebench module")
        print("Make sure the main codebench file is in the same directory")
        sys.exit(1)

# Correct solutions for all problems
SOLUTIONS = {
    1: {  # Two Sum
        "python": """
from typing import List

class Solution:
    def twoSum(self, nums: List[int], target: int) -> List[int]:
        seen = {}
        for i, num in enumerate(nums):
            complement = target - num
            if complement in seen:
                return [seen[complement], i]
            seen[num] = i
        return []
""",
        "java": """
import java.util.HashMap;
import java.util.Map;

class Solution {
    public int[] twoSum(int[] nums, int target) {
        Map<Integer, Integer> map = new HashMap<>();
        for (int i = 0; i < nums.length; i++) {
            int complement = target - nums[i];
            if (map.containsKey(complement)) {
                return new int[] { map.get(complement), i };
            }
            map.put(nums[i], i);
        }
        return new int[] {};
    }
}
"""
    },
    2: {  # Add Two Numbers
        "python": """
from typing import Optional

class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next

class Solution:
    def addTwoNumbers(self, l1: Optional[ListNode], l2: Optional[ListNode]) -> Optional[ListNode]:
        dummy = ListNode(0)
        current = dummy
        carry = 0

        while l1 or l2 or carry:
            val1 = l1.val if l1 else 0
            val2 = l2.val if l2 else 0

            total = val1 + val2 + carry
            carry = total // 10
            current.next = ListNode(total % 10)
            current = current.next

            if l1:
                l1 = l1.next
            if l2:
                l2 = l2.next

        return dummy.next
""",
        "java": """
// Note: ListNode class is already defined in helper_classes from YAML
// So we don't define it here to avoid duplication

class Solution {
    public ListNode addTwoNumbers(ListNode l1, ListNode l2) {
        ListNode dummy = new ListNode(0);
        ListNode current = dummy;
        int carry = 0;

        while (l1 != null || l2 != null || carry != 0) {
            int val1 = (l1 != null) ? l1.val : 0;
            int val2 = (l2 != null) ? l2.val : 0;

            int sum = val1 + val2 + carry;
            carry = sum / 10;
            current.next = new ListNode(sum % 10);
            current = current.next;

            if (l1 != null) l1 = l1.next;
            if (l2 != null) l2 = l2.next;
        }

        return dummy.next;
    }
}
"""
    },
    3: {  # Longest Substring Without Repeating Characters
        "python": """
class Solution:
    def lengthOfLongestSubstring(self, s: str) -> int:
        char_set = set()
        left = 0
        max_length = 0

        for right in range(len(s)):
            while s[right] in char_set:
                char_set.remove(s[left])
                left += 1
            char_set.add(s[right])
            max_length = max(max_length, right - left + 1)

        return max_length
""",
        "java": """
import java.util.HashSet;
import java.util.Set;

class Solution {
    public int lengthOfLongestSubstring(String s) {
        Set<Character> charSet = new HashSet<>();
        int left = 0;
        int maxLength = 0;

        for (int right = 0; right < s.length(); right++) {
            while (charSet.contains(s.charAt(right))) {
                charSet.remove(s.charAt(left));
                left++;
            }
            charSet.add(s.charAt(right));
            maxLength = Math.max(maxLength, right - left + 1);
        }

        return maxLength;
    }
}
"""
    },
    4: {  # Valid Parentheses
        "python": """
class Solution:
    def isValid(self, s: str) -> bool:
        stack = []
        mapping = {')': '(', '}': '{', ']': '['}

        for char in s:
            if char in mapping:
                if not stack or stack.pop() != mapping[char]:
                    return False
            else:
                stack.append(char)

        return len(stack) == 0
""",
        "java": """
import java.util.Stack;

class Solution {
    public boolean isValid(String s) {
        Stack<Character> stack = new Stack<>();

        for (char c : s.toCharArray()) {
            if (c == '(' || c == '{' || c == '[') {
                stack.push(c);
            } else {
                if (stack.isEmpty()) return false;
                char top = stack.pop();
                if ((c == ')' && top != '(') ||
                    (c == '}' && top != '{') ||
                    (c == ']' && top != '[')) {
                    return false;
                }
            }
        }

        return stack.isEmpty();
    }
}
"""
    },
    5: {  # Best Time to Buy and Sell Stock
        "python": """
from typing import List

class Solution:
    def maxProfit(self, prices: List[int]) -> int:
        if not prices:
            return 0

        min_price = prices[0]
        max_profit = 0

        for price in prices[1:]:
            max_profit = max(max_profit, price - min_price)
            min_price = min(min_price, price)

        return max_profit
""",
        "java": """
class Solution {
    public int maxProfit(int[] prices) {
        if (prices.length == 0) return 0;

        int minPrice = prices[0];
        int maxProfit = 0;

        for (int i = 1; i < prices.length; i++) {
            maxProfit = Math.max(maxProfit, prices[i] - minPrice);
            minPrice = Math.min(minPrice, prices[i]);
        }

        return maxProfit;
    }
}
"""
    },
    6: {  # Sudoku Solver
        "python": """
from typing import List

class Solution:
    def solveSudoku(self, board: List[List[str]]) -> None:
        def is_valid(board, row, col, num):
            # Check row
            for x in range(9):
                if board[row][x] == num:
                    return False

            # Check column
            for x in range(9):
                if board[x][col] == num:
                    return False

            # Check 3x3 box
            start_row = row - row % 3
            start_col = col - col % 3
            for i in range(3):
                for j in range(3):
                    if board[i + start_row][j + start_col] == num:
                        return False

            return True

        def solve():
            for i in range(9):
                for j in range(9):
                    if board[i][j] == '.':
                        for num in '123456789':
                            if is_valid(board, i, j, num):
                                board[i][j] = num
                                if solve():
                                    return True
                                board[i][j] = '.'
                        return False
            return True

        solve()
""",
        "java": """
class Solution {
    public void solveSudoku(char[][] board) {
        solve(board);
    }

    private boolean solve(char[][] board) {
        for (int i = 0; i < 9; i++) {
            for (int j = 0; j < 9; j++) {
                if (board[i][j] == '.') {
                    for (char num = '1'; num <= '9'; num++) {
                        if (isValid(board, i, j, num)) {
                            board[i][j] = num;
                            if (solve(board)) {
                                return true;
                            }
                            board[i][j] = '.';
                        }
                    }
                    return false;
                }
            }
        }
        return true;
    }

    private boolean isValid(char[][] board, int row, int col, char num) {
        // Check row
        for (int x = 0; x < 9; x++) {
            if (board[row][x] == num) {
                return false;
            }
        }

        // Check column
        for (int x = 0; x < 9; x++) {
            if (board[x][col] == num) {
                return false;
            }
        }

        // Check 3x3 box
        int startRow = row - row % 3;
        int startCol = col - col % 3;
        for (int i = 0; i < 3; i++) {
            for (int j = 0; j < 3; j++) {
                if (board[i + startRow][j + startCol] == num) {
                    return false;
                }
            }
        }

        return true;
    }
}
"""
    },
    21: {  # Word Ladder
        "python": """
from typing import List
from collections import deque

class Solution:
    def ladderLength(self, beginWord: str, endWord: str, wordList: List[str]) -> int:
        if endWord not in wordList:
            return 0
        
        wordSet = set(wordList)
        queue = deque([(beginWord, 1)])
        visited = {beginWord}
        
        while queue:
            word, length = queue.popleft()
            
            if word == endWord:
                return length
            
            # Try changing each character
            for i in range(len(word)):
                for c in 'abcdefghijklmnopqrstuvwxyz':
                    if c != word[i]:
                        newWord = word[:i] + c + word[i+1:]
                        
                        if newWord in wordSet and newWord not in visited:
                            visited.add(newWord)
                            queue.append((newWord, length + 1))
        
        return 0
""",
        "java": """
import java.util.*;

class Solution {
    public int ladderLength(String beginWord, String endWord, List<String> wordList) {
        if (!wordList.contains(endWord)) {
            return 0;
        }
        
        Set<String> wordSet = new HashSet<>(wordList);
        Queue<String[]> queue = new LinkedList<>();
        Set<String> visited = new HashSet<>();
        
        queue.offer(new String[]{beginWord, "1"});
        visited.add(beginWord);
        
        while (!queue.isEmpty()) {
            String[] current = queue.poll();
            String word = current[0];
            int length = Integer.parseInt(current[1]);
            
            if (word.equals(endWord)) {
                return length;
            }
            
            // Try changing each character
            for (int i = 0; i < word.length(); i++) {
                for (char c = 'a'; c <= 'z'; c++) {
                    if (c != word.charAt(i)) {
                        String newWord = word.substring(0, i) + c + word.substring(i + 1);
                        
                        if (wordSet.contains(newWord) && !visited.contains(newWord)) {
                            visited.add(newWord);
                            queue.offer(new String[]{newWord, String.valueOf(length + 1)});
                        }
                    }
                }
            }
        }
        
        return 0;
    }
}
"""
    },
    20: {  # Insert Interval
        "python": """
from typing import List

class Solution:
    def insert(self, intervals: List[List[int]], newInterval: List[int]) -> List[List[int]]:
        result = []
        i = 0
        
        # Add all intervals that come before newInterval
        while i < len(intervals) and intervals[i][1] < newInterval[0]:
            result.append(intervals[i])
            i += 1
        
        # Merge overlapping intervals
        while i < len(intervals) and intervals[i][0] <= newInterval[1]:
            newInterval[0] = min(newInterval[0], intervals[i][0])
            newInterval[1] = max(newInterval[1], intervals[i][1])
            i += 1
        
        # Add the merged interval
        result.append(newInterval)
        
        # Add remaining intervals
        while i < len(intervals):
            result.append(intervals[i])
            i += 1
        
        return result
""",
        "java": """
class Solution {
    public int[][] insert(int[][] intervals, int[] newInterval) {
        List<int[]> result = new ArrayList<>();
        int i = 0;
        
        // Add all intervals that come before newInterval
        while (i < intervals.length && intervals[i][1] < newInterval[0]) {
            result.add(intervals[i]);
            i++;
        }
        
        // Merge overlapping intervals
        while (i < intervals.length && intervals[i][0] <= newInterval[1]) {
            newInterval[0] = Math.min(newInterval[0], intervals[i][0]);
            newInterval[1] = Math.max(newInterval[1], intervals[i][1]);
            i++;
        }
        
        // Add the merged interval
        result.add(newInterval);
        
        // Add remaining intervals
        while (i < intervals.length) {
            result.add(intervals[i]);
            i++;
        }
        
        return result.toArray(new int[result.size()][]);
    }
}
"""
    },
    15: {  # Group Anagrams
        "python": """
from typing import List
from collections import defaultdict

class Solution:
    def groupAnagrams(self, strs: List[str]) -> List[List[str]]:
        anagram_groups = defaultdict(list)
        
        for s in strs:
            # Sort the characters to create a key
            key = ''.join(sorted(s))
            anagram_groups[key].append(s)
        
        return list(anagram_groups.values())
""",
        "java": """
import java.util.*;

class Solution {
    public List<List<String>> groupAnagrams(String[] strs) {
        Map<String, List<String>> anagramGroups = new HashMap<>();
        
        for (String s : strs) {
            // Sort the characters to create a key
            char[] chars = s.toCharArray();
            Arrays.sort(chars);
            String key = new String(chars);
            
            anagramGroups.computeIfAbsent(key, k -> new ArrayList<>()).add(s);
        }
        
        return new ArrayList<>(anagramGroups.values());
    }
}
"""
    },
    8: {  # Container With Most Water
        "python": """
from typing import List

class Solution:
    def maxArea(self, height: List[int]) -> int:
        left, right = 0, len(height) - 1
        max_area = 0
        
        while left < right:
            # Calculate area with current pointers
            width = right - left
            current_height = min(height[left], height[right])
            area = width * current_height
            max_area = max(max_area, area)
            
            # Move pointer with smaller height
            if height[left] < height[right]:
                left += 1
            else:
                right -= 1
        
        return max_area
""",
        "java": """
class Solution {
    public int maxArea(int[] height) {
        int left = 0, right = height.length - 1;
        int maxArea = 0;
        
        while (left < right) {
            // Calculate area with current pointers
            int width = right - left;
            int currentHeight = Math.min(height[left], height[right]);
            int area = width * currentHeight;
            maxArea = Math.max(maxArea, area);
            
            // Move pointer with smaller height
            if (height[left] < height[right]) {
                left++;
            } else {
                right--;
            }
        }
        
        return maxArea;
    }
}
"""
    },
    9: {  # 3Sum
        "python": """
from typing import List

class Solution:
    def threeSum(self, nums: List[int]) -> List[List[int]]:
        nums.sort()
        result = []
        
        for i in range(len(nums) - 2):
            # Skip duplicates for first number
            if i > 0 and nums[i] == nums[i - 1]:
                continue
            
            left, right = i + 1, len(nums) - 1
            
            while left < right:
                total = nums[i] + nums[left] + nums[right]
                
                if total == 0:
                    result.append([nums[i], nums[left], nums[right]])
                    
                    # Skip duplicates for second number
                    while left < right and nums[left] == nums[left + 1]:
                        left += 1
                    # Skip duplicates for third number
                    while left < right and nums[right] == nums[right - 1]:
                        right -= 1
                    
                    left += 1
                    right -= 1
                elif total < 0:
                    left += 1
                else:
                    right -= 1
        
        return result
""",
        "java": """
import java.util.*;

class Solution {
    public List<List<Integer>> threeSum(int[] nums) {
        Arrays.sort(nums);
        List<List<Integer>> result = new ArrayList<>();
        
        for (int i = 0; i < nums.length - 2; i++) {
            // Skip duplicates for first number
            if (i > 0 && nums[i] == nums[i - 1]) {
                continue;
            }
            
            int left = i + 1, right = nums.length - 1;
            
            while (left < right) {
                int total = nums[i] + nums[left] + nums[right];
                
                if (total == 0) {
                    result.add(Arrays.asList(nums[i], nums[left], nums[right]));
                    
                    // Skip duplicates for second number
                    while (left < right && nums[left] == nums[left + 1]) {
                        left++;
                    }
                    // Skip duplicates for third number
                    while (left < right && nums[right] == nums[right - 1]) {
                        right--;
                    }
                    
                    left++;
                    right--;
                } else if (total < 0) {
                    left++;
                } else {
                    right--;
                }
            }
        }
        
        return result;
    }
}
"""
    },
    16: {  # Maximum Subarray
        "python": """
from typing import List

class Solution:
    def maxSubArray(self, nums: List[int]) -> int:
        max_sum = current_sum = nums[0]
        
        for i in range(1, len(nums)):
            # Either extend existing subarray or start new one
            current_sum = max(nums[i], current_sum + nums[i])
            max_sum = max(max_sum, current_sum)
        
        return max_sum
""",
        "java": """
class Solution {
    public int maxSubArray(int[] nums) {
        int maxSum = nums[0];
        int currentSum = nums[0];
        
        for (int i = 1; i < nums.length; i++) {
            // Either extend existing subarray or start new one
            currentSum = Math.max(nums[i], currentSum + nums[i]);
            maxSum = Math.max(maxSum, currentSum);
        }
        
        return maxSum;
    }
}
"""
    },
    18: {  # Jump Game
        "python": """
from typing import List

class Solution:
    def canJump(self, nums: List[int]) -> bool:
        max_reach = 0
        
        for i in range(len(nums)):
            # If current position is beyond max reach, can't reach here
            if i > max_reach:
                return False
            
            # Update max reach
            max_reach = max(max_reach, i + nums[i])
            
            # If we can reach the end, return True
            if max_reach >= len(nums) - 1:
                return True
        
        return True
""",
        "java": """
class Solution {
    public boolean canJump(int[] nums) {
        int maxReach = 0;
        
        for (int i = 0; i < nums.length; i++) {
            // If current position is beyond max reach, can't reach here
            if (i > maxReach) {
                return false;
            }
            
            // Update max reach
            maxReach = Math.max(maxReach, i + nums[i]);
            
            // If we can reach the end, return True
            if (maxReach >= nums.length - 1) {
                return true;
            }
        }
        
        return true;
    }
}
"""
    },
    19: {  # Merge Intervals
        "python": """
from typing import List

class Solution:
    def merge(self, intervals: List[List[int]]) -> List[List[int]]:
        if not intervals:
            return []
        
        # Sort intervals by start time
        intervals.sort(key=lambda x: x[0])
        
        merged = [intervals[0]]
        
        for current in intervals[1:]:
            last = merged[-1]
            
            # If current interval overlaps with last merged interval
            if current[0] <= last[1]:
                # Merge intervals
                last[1] = max(last[1], current[1])
            else:
                # No overlap, add current interval
                merged.append(current)
        
        return merged
""",
        "java": """
import java.util.*;

class Solution {
    public int[][] merge(int[][] intervals) {
        if (intervals.length == 0) {
            return new int[0][];
        }
        
        // Sort intervals by start time
        Arrays.sort(intervals, (a, b) -> Integer.compare(a[0], b[0]));
        
        List<int[]> merged = new ArrayList<>();
        merged.add(intervals[0]);
        
        for (int i = 1; i < intervals.length; i++) {
            int[] current = intervals[i];
            int[] last = merged.get(merged.size() - 1);
            
            // If current interval overlaps with last merged interval
            if (current[0] <= last[1]) {
                // Merge intervals
                last[1] = Math.max(last[1], current[1]);
            } else {
                // No overlap, add current interval
                merged.add(current);
            }
        }
        
        return merged.toArray(new int[merged.size()][]);
    }
}
"""
    }
}


class TestCodeBench:
    """Test class for CodeBench problems"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Load problems from YAML before each test"""
        self.yaml_path = "codebench_problems.yml"

        # Try to find the YAML file
        if not os.path.exists(self.yaml_path):
            alt_path = os.path.join(os.path.dirname(__file__), self.yaml_path)
            if os.path.exists(alt_path):
                self.yaml_path = alt_path
            else:
                pytest.skip(f"Cannot find {self.yaml_path}")

        with open(self.yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        self.problems = data['problems']

    def get_test_params(self):
        """Generate test parameters for all problems and languages"""
        params = []
        for problem in self.problems:
            problem_id = problem['id']
            if problem_id in SOLUTIONS:
                for language in ['python', 'java']:
                    if language in SOLUTIONS[problem_id]:
                        params.append((problem, language))
        return params

    @pytest.mark.parametrize("problem,language", [
        (p, l) for p in yaml.safe_load(open("codebench_problems.yml", 'r'))['problems']
        for l in ['python', 'java'] if p['id'] in SOLUTIONS and l in SOLUTIONS[p['id']]
    ])
    def test_solution(self, problem, language):
        """Test a solution for a specific problem and language"""
        problem_id = problem['id']
        problem_title = problem['title']

        # Get the solution code
        solution_code = SOLUTIONS[problem_id][language]

        # Get problem metadata
        method_info = problem.get('method_info', {}).get(language, {})
        comparison_strategy = problem.get('comparison_strategy', 'exact')
        test_cases = problem.get('test_cases', [])

        print(f"\nTesting Problem {problem_id}: {problem_title} ({language})")
        print(f"Number of test cases: {len(test_cases)}")

        # Run each test case
        for i, test_case in enumerate(test_cases):
            print(f"\n  Test case {i + 1}:")
            print(f"    Input: {test_case['input']}")
            print(f"    Expected: {test_case['expected']}")

            # Run the test using the imported function
            if language == 'python':
                result = run_python_test(
                    solution_code,
                    test_case['input'],
                    test_case['expected'],
                    method_info,
                    comparison_strategy
                )
            else:  # java
                result = run_java_test(
                    solution_code,
                    test_case['input'],
                    test_case['expected'],
                    method_info,
                    comparison_strategy
                )

            print(f"    Actual: {result['actual']}")
            print(f"    Passed: {result['passed']}")

            if result['error']:
                print(f"    Error: {result['error']}")

            # Assert the test passed
            assert result['passed'], (
                f"Test failed for {problem_title} ({language}):\n"
                f"Input: {test_case['input']}\n"
                f"Expected: {test_case['expected']}\n"
                f"Actual: {result['actual']}\n"
                f"Error: {result.get('error', 'None')}"
            )

    def test_yaml_structure(self):
        """Test that the YAML file has the expected structure"""
        assert len(self.problems) > 0, "No problems found in YAML"

        for problem in self.problems:
            # Check required fields
            assert 'id' in problem, f"Problem missing 'id' field"
            assert 'title' in problem, f"Problem {problem.get('id', '?')} missing 'title'"
            assert 'difficulty' in problem, f"Problem {problem.get('id', '?')} missing 'difficulty'"
            assert 'method_info' in problem, f"Problem {problem.get('id', '?')} missing 'method_info'"
            assert 'test_cases' in problem, f"Problem {problem.get('id', '?')} missing 'test_cases'"

            # Check method_info structure
            method_info = problem['method_info']
            for lang in ['python', 'java']:
                if lang in method_info:
                    assert 'method_name' in method_info[lang], (
                        f"Problem {problem['id']} missing method_name for {lang}"
                    )
                    assert 'parameters' in method_info[lang], (
                        f"Problem {problem['id']} missing parameters for {lang}"
                    )
                    assert 'return_type' in method_info[lang], (
                        f"Problem {problem['id']} missing return_type for {lang}"
                    )


if __name__ == "__main__":
    # Run tests with pytest
    import subprocess

    result = subprocess.run([sys.executable, "-m", "pytest", __file__, "-v"],
                            capture_output=False, text=True)
    sys.exit(result.returncode)