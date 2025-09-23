# Monkey patch the validation interceptor to add debug prints
import agent_actions.interceptors.validation_interceptor as vi
from agent_actions.interceptors.validation_interceptor import ValidationInterceptor

# Store original methods
original_configure = ValidationInterceptor.configure
original_intercept = ValidationInterceptor.intercept

def debug_configure(self, config):
    print(f"🔧 INTERCEPTOR CONFIGURE DEBUG:")
    print(f"   Config received: {config}")
    print(f"   Validator name: {config.get('validator')}")
    return original_configure(self, config)

def debug_intercept(self, response, context):
    print(f"🔍 INTERCEPTOR INTERCEPT DEBUG:")
    print(f"   Response type: {type(response)}")
    print(f"   Response preview: {str(response)[:200]}...")
    print(f"   Context keys: {list(context.keys())}")
    result = original_intercept(self, response, context)
    print(f"   Interceptor result: continue={result.continue_processing}, retry={bool(result.retry_context)}")
    return result

# Monkey patch the methods
ValidationInterceptor.configure = debug_configure
ValidationInterceptor.intercept = debug_intercept

print("🐛 Debug interceptor patches applied!")

