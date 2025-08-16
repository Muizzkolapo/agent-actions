"""
SQL injection prevention tests for WHERE clause filtering.

Tests specific SQL injection attack vectors and prevention mechanisms.
"""

import pytest
from agent_actions.security import validate_where_clause, is_safe_where_clause


class TestSQLInjectionPrevention:
    """Test prevention of SQL injection-like attacks in WHERE clauses."""
    
    def test_classic_sql_injection_patterns(self):
        """Test detection of classic SQL injection patterns."""
        classic_injections = [
            # Boolean-based blind SQL injection
            "field = 'value' OR 1=1",
            "field = 'value' OR 'a'='a'",
            "field = 'value' OR 1=1 --",
            "field = 'value' OR 1=1 #",
            
            # Union-based SQL injection
            "field = 'value' UNION SELECT username FROM users",
            "field = 'value' UNION ALL SELECT password FROM admin",
            "field = 'value' UNION SELECT 1,2,3,4,5",
            
            # Time-based blind SQL injection
            "field = 'value'; WAITFOR DELAY '00:00:05'",
            "field = 'value' AND SLEEP(5)",
            "field = 'value' AND BENCHMARK(5000000,MD5(1))",
            
            # Stacked queries
            "field = 'value'; DROP TABLE users;",
            "field = 'value'; INSERT INTO log VALUES ('hacked');",
            "field = 'value'; UPDATE users SET password='hacked';",
            "field = 'value'; DELETE FROM users WHERE 1=1;",
            
            # Comment-based injection
            "field = 'value'/*comment*/AND 1=1",
            "field = 'value' -- comment",
            "field = 'value' # comment",
            
            # Error-based SQL injection
            "field = 'value' AND (SELECT * FROM (SELECT COUNT(*),CONCAT(version(),FLOOR(RAND(0)*2))x FROM information_schema.tables GROUP BY x)a)",
            "field = 'value' AND extractvalue(1,concat(0x7e,(SELECT user()),0x7e))",
            
            # Stored procedure injection
            "field = 'value'; EXEC xp_cmdshell('dir')",
            "field = 'value'; EXEC sp_executesql N'SELECT * FROM users'",
            
            # Second-order SQL injection
            "field = 'O''Reilly'",  # Escaped quote that could be dangerous in certain contexts
        ]
        
        for injection in classic_injections:
            assert not is_safe_where_clause(injection), f"Failed to detect injection: {injection}"
            
            result = validate_where_clause(injection)
            assert not result.is_valid, f"Injection marked as valid: {injection}"
            assert len(result.errors) > 0, f"No errors reported for injection: {injection}"
    
    def test_advanced_sql_injection_techniques(self):
        """Test detection of advanced SQL injection techniques."""
        advanced_injections = [
            # Hex encoding
            "field = 0x61646D696E",  # 'admin' in hex
            
            # Char function
            "field = CHAR(97,100,109,105,110)",  # 'admin' using CHAR
            
            # Concatenation
            "field = 'ad'+'min'",
            "field = CONCAT('ad','min')",
            
            # Case manipulation
            "field = 'value' UnIoN SeLeCt * FrOm users",
            
            # Whitespace variations
            "field = 'value'\t\tOR\t\t1=1",
            "field = 'value'\nOR\n1=1",
            "field = 'value'/**/OR/**/1=1",
            
            # Function-based injection
            "field = 'value' AND ASCII(SUBSTRING((SELECT user()),1,1))>64",
            "field = 'value' AND LENGTH(database())>0",
            
            # Conditional injection
            "field = IF(1=1,'value','other')",
            "field = CASE WHEN 1=1 THEN 'value' ELSE 'other' END",
            
            # Subquery injection
            "field = (SELECT 'value' FROM dual)",
            "field = 'value' AND (SELECT COUNT(*) FROM users)>0",
        ]
        
        for injection in advanced_injections:
            assert not is_safe_where_clause(injection), f"Failed to detect advanced injection: {injection}"
    
    def test_database_specific_injections(self):
        """Test detection of database-specific injection patterns."""
        
        # MySQL specific
        mysql_injections = [
            "field = 'value' AND @@version",
            "field = 'value' AND user()",
            "field = 'value' AND database()",
            "field = 'value' LIMIT 1,1",
            "field = 'value' INTO OUTFILE '/tmp/file'",
            "field = 'value' AND LOAD_FILE('/etc/passwd')",
        ]
        
        # PostgreSQL specific
        postgresql_injections = [
            "field = 'value' AND version()",
            "field = 'value' AND current_user",
            "field = 'value' AND current_database()",
            "field = 'value'; COPY users TO '/tmp/file'",
        ]
        
        # SQL Server specific
        sqlserver_injections = [
            "field = 'value' AND @@version",
            "field = 'value' AND user_name()",
            "field = 'value' AND db_name()",
            "field = 'value'; EXEC master..xp_cmdshell 'dir'",
            "field = 'value' AND HAS_DBACCESS('master')",
        ]
        
        # Oracle specific
        oracle_injections = [
            "field = 'value' AND user",
            "field = 'value' FROM dual",
            "field = 'value' AND SYS.DATABASE_NAME",
            "field = 'value' UNION SELECT null FROM dual",
        ]
        
        all_injections = mysql_injections + postgresql_injections + sqlserver_injections + oracle_injections
        
        for injection in all_injections:
            assert not is_safe_where_clause(injection), f"Failed to detect DB-specific injection: {injection}"
    
    def test_injection_in_different_contexts(self):
        """Test injection attempts in different parts of WHERE clauses."""
        
        # Injection in field names
        field_injections = [
            "users.username OR 1=1 == 'value'",
            "table; DROP TABLE users; == 'value'",
        ]
        
        # Injection in operators
        operator_injections = [
            "field OR 1=1 OR field == 'value'",
            "field UNION SELECT * FROM users 'value'",
        ]
        
        # Injection in values
        value_injections = [
            "field == 'value'; DROP TABLE users;--'",
            "field == 'value' OR 1=1 --'",
            "field IN ['value', 'other'; DROP TABLE users;--']",
        ]
        
        all_contexts = field_injections + operator_injections + value_injections
        
        for injection in all_contexts:
            result = validate_where_clause(injection)
            assert not result.is_valid, f"Context injection not detected: {injection}"
    
    def test_encoded_injection_attempts(self):
        """Test detection of encoded injection attempts."""
        encoded_injections = [
            # URL encoding
            "field = 'value'%20OR%201=1",
            "field = 'value'%3B%20DROP%20TABLE%20users%3B",
            
            # Double URL encoding
            "field = 'value'%2520OR%25201=1",
            
            # Unicode encoding
            "field = 'value' \u004F\u0052 1=1",  # OR in Unicode
            
            # HTML entity encoding
            "field = 'value'&nbsp;OR&nbsp;1=1",
            
            # Mixed encoding
            "field = 'value'%20\u004F\u0052%201=1",
        ]
        
        for injection in encoded_injections:
            # The validator should either detect these as suspicious or 
            # they should fail during parsing
            result = validate_where_clause(injection)
            if result.is_valid:
                # If somehow considered valid, should generate warnings
                assert len(result.warnings) > 0, f"Encoded injection had no warnings: {injection}"
    
    def test_legitimate_clauses_not_flagged(self):
        """Test that legitimate WHERE clauses are not flagged as injections."""
        legitimate_clauses = [
            "status == 'active'",
            "name != 'admin'",
            "age >= 18 AND status == 'verified'",
            "category IN ['tech', 'science', 'health']",
            "title CONTAINS 'SQL Tutorial'",  # Contains 'SQL' but is legitimate
            "description NOT CONTAINS 'spam'",
            "created_date >= '2023-01-01'",
            "score > 80 AND rank <= 10",
            "user.profile.verified == true",
            "metadata.tags CONTAINS 'important'",
            "price BETWEEN 10 AND 100",  # Even if BETWEEN is not fully supported
        ]
        
        for clause in legitimate_clauses:
            result = validate_where_clause(clause)
            # Should be valid or have only minor warnings, not security errors
            if not result.is_valid:
                security_errors = [err for err in result.errors if 'injection' in err.lower()]
                assert len(security_errors) == 0, f"Legitimate clause flagged as injection: {clause}"
    
    def test_case_sensitivity_in_detection(self):
        """Test that injection detection works regardless of case."""
        base_injection = "field = 'value' UNION SELECT * FROM users"
        
        case_variations = [
            base_injection.upper(),
            base_injection.lower(),
            base_injection.title(),
            "Field = 'Value' Union Select * From Users",  # Mixed case
            "FIELD = 'value' union SELECT * from USERS",  # Random case
        ]
        
        for variation in case_variations:
            assert not is_safe_where_clause(variation), f"Case variation not detected: {variation}"
    
    def test_whitespace_evasion_detection(self):
        """Test detection of whitespace evasion techniques."""
        whitespace_evasions = [
            "field='value'OR 1=1",  # No spaces
            "field = 'value'\tOR\t1=1",  # Tabs
            "field = 'value'\nOR\n1=1",  # Newlines
            "field = 'value'\r\nOR\r\n1=1",  # Windows line endings
            "field = 'value'/**/OR/**/1=1",  # Comments as whitespace
            "field = 'value'  OR  1=1",  # Multiple spaces
            "field = 'value' \t\n OR \t\n 1=1",  # Mixed whitespace
        ]
        
        for evasion in whitespace_evasions:
            assert not is_safe_where_clause(evasion), f"Whitespace evasion not detected: {evasion}"
    
    def test_quote_evasion_detection(self):
        """Test detection of quote evasion techniques."""
        quote_evasions = [
            "field = \"value\" OR 1=1",  # Double quotes instead of single
            "field = `value` OR 1=1",   # Backticks (MySQL style)
            "field = 'value\\' OR 1=1 --'",  # Escaped quote
            "field = 'value''OR 1=1',", # SQL quote doubling
            "field = CHAR(118,97,108,117,101) OR 1=1",  # Character encoding
        ]
        
        for evasion in quote_evasions:
            result = validate_where_clause(evasion)
            # Should either be invalid or have warnings
            if result.is_valid:
                assert len(result.warnings) > 0, f"Quote evasion had no warnings: {evasion}"
            else:
                assert not result.is_valid, f"Quote evasion not properly handled: {evasion}"