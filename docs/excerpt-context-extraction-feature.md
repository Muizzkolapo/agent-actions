# Excerpt-Based Context Extraction Feature

## Overview

Excerpt-based context extraction is a precision text processing feature that uses a known text snippet (excerpt) as an anchor to locate and extract relevant context windows from larger documents. Instead of processing entire documents or using mechanical chunking, this feature enables agents to focus on semantically relevant sections, improving both accuracy and efficiency.

## Core Concept

The feature works by:
1. **Anchor Location**: Uses a provided excerpt to find its exact location within a larger text (page_content)
2. **Context Window Extraction**: Extracts a configurable boundary of text around the located excerpt
3. **Focused Processing**: Provides agents with precisely relevant context instead of full documents

```
Full Document: [----excerpt location----]
                    ↓
Context Window: [--relevant context--]
                    ↓
Agent Processing: Enhanced accuracy + reduced tokens
```

## Why Use This Feature?

### Current Limitations
- **Token Waste**: Processing entire documents when only specific sections are relevant
- **Context Noise**: Irrelevant information dilutes agent focus and accuracy
- **Mechanical Chunking**: Fixed-size chunks often split semantic units inappropriately
- **Processing Inefficiency**: Higher costs and slower processing for unnecessary content

### Benefits
- **Cost Reduction**: 60-80% reduction in token usage by processing only relevant sections
- **Improved Accuracy**: Agents work with precisely relevant context vs noisy full documents
- **Semantic Preservation**: Maintains meaningful text boundaries around relevant content
- **Flexible Configuration**: Adaptable to different use cases and content types

## Use Cases

### 1. Document Q&A Systems
**Scenario**: User has a specific quote or excerpt from a document and needs analysis of the surrounding context.
```yaml
# User provides: excerpt from research paper
# System locates: exact position in full paper
# Agent processes: surrounding methodology and findings
```

### 2. Citation Verification
**Scenario**: Verify quotes and analyze their context within source materials.
```yaml
# Input: Quoted text from article
# Process: Find quote location + surrounding paragraphs
# Output: Citation verification + contextual analysis
```

### 3. Code Documentation Analysis
**Scenario**: Analyze specific code snippets within larger codebases.
```yaml
# Input: Function signature or code excerpt
# Process: Locate in codebase + extract related functions/comments
# Output: Comprehensive code analysis with dependencies
```

### 4. Research Paper Processing
**Scenario**: Focus on specific findings or methodologies within academic papers.
```yaml
# Input: Key finding excerpt from abstract/conclusion
# Process: Locate in paper + extract methodology context
# Output: Detailed analysis of research approach and results
```

### 5. Legal Document Analysis
**Scenario**: Analyze specific clauses within contracts or legal documents.
```yaml
# Input: Contract clause excerpt
# Process: Find clause + extract related sections
# Output: Comprehensive clause analysis with dependencies
```

## Configuration

### Basic Configuration
```yaml
excerpt_config:
  enabled: true
  search_mode: "regex"              # Search strategy
  context_window: 500               # Context size around excerpt
  boundary_type: "characters"       # Boundary measurement unit
  fallback_strategy: "full_content" # What to do if excerpt not found
```

### Advanced Configuration
```yaml
excerpt_config:
  enabled: true
  search_mode: "fuzzy"
  fuzzy_threshold: 0.85             # Similarity threshold for fuzzy matching
  context_window: 800
  boundary_type: "sentences"        # Preserve sentence boundaries
  window_expansion:
    before: 300                     # Asymmetric windows
    after: 500
  overlap_handling: "merge"         # How to handle overlapping contexts
  preprocessing:
    normalize_whitespace: true
    case_insensitive: true
  fallback_strategy: "chunking"     # Fall back to traditional chunking
  chunk_fallback:
    chunk_size: 1000
    overlap: 200
```

## Search Modes

### 1. Exact Match (`exact`)
```python
# Perfect string matching
search_mode: "exact"
case_sensitive: false  # Optional
```

### 2. Regex Pattern (`regex`)
```python
# Flexible pattern matching
search_mode: "regex"
pattern_flags: ["IGNORECASE", "MULTILINE"]  # Optional regex flags
```

### 3. Fuzzy Matching (`fuzzy`)
```python
# Handles typos and variations
search_mode: "fuzzy"
fuzzy_threshold: 0.85  # Similarity threshold (0.0-1.0)
algorithm: "levenshtein"  # or "jaro_winkler", "cosine"
```

### 4. Semantic Search (`semantic`)
```python
# Vector-based similarity matching
search_mode: "semantic"
embedding_model: "sentence-transformers/all-MiniLM-L6-v2"
similarity_threshold: 0.75
```

## Boundary Types

### 1. Character-based (`characters`)
```python
boundary_type: "characters"
context_window: 500  # 500 characters before and after
```

### 2. Token-based (`tokens`)
```python
boundary_type: "tokens"
context_window: 100  # 100 tokens before and after
tokenizer_model: "cl100k_base"  # OpenAI tokenizer
```

### 3. Sentence-based (`sentences`)
```python
boundary_type: "sentences"
context_window: 5  # 5 sentences before and after
sentence_splitter: "spacy"  # or "nltk", "custom"
```

### 4. Paragraph-based (`paragraphs`)
```python
boundary_type: "paragraphs"
context_window: 2  # 2 paragraphs before and after
paragraph_delimiter: "\n\n"  # Custom delimiter
```

## Fallback Strategies

### 1. Full Content (`full_content`)
Use the entire page_content if excerpt not found.
```python
fallback_strategy: "full_content"
```

### 2. Traditional Chunking (`chunking`)
Fall back to existing chunking mechanism.
```python
fallback_strategy: "chunking"
chunk_fallback:
  chunk_size: 1000
  overlap: 200
  method: "tiktoken"
```

### 3. Error Handling (`error`)
Raise an error if excerpt not found.
```python
fallback_strategy: "error"
error_message: "Excerpt not found in source content"
```

### 4. Skip Record (`skip`)
Skip processing this record entirely.
```python
fallback_strategy: "skip"
log_skipped: true
```

## Integration with Existing System

### 1. Agent Configuration
```yaml
agents:
  - agent_type: DocumentAnalyzer
    # ... existing config ...
    excerpt_config:
      enabled: true
      search_mode: "fuzzy"
      context_window: 400
      boundary_type: "sentences"
    side_collection:
      - id
      - url
      - excerpt        # The search anchor
      - page_content   # Full text to search within
    remove_collection:
      - raw_content    # Remove unnecessary fields
    prompt: $analysis.excerpt_focused
```

### 2. Data Structure Requirements
```python
# Input data format
{
  "id": "doc_001",
  "excerpt": "The methodology employed in this study...",
  "page_content": "Full document text containing the excerpt...",
  "url": "https://source.url",
  # ... other fields
}

# Output data format (after processing)
{
  "id": "doc_001",
  "excerpt": "The methodology employed in this study...",
  "focused_content": "Extracted context window around excerpt...",
  "context_metadata": {
    "match_position": {"start": 1250, "end": 1285},
    "context_bounds": {"start": 950, "end": 1585},
    "extraction_method": "fuzzy_match",
    "confidence_score": 0.92
  },
  "url": "https://source.url"
}
```

### 3. Pipeline Integration
The feature integrates with existing pipeline stages:

#### Context Preprocessing Stage
```python
# In context_preprocessor.py
class ContextPreprocessor:
    @staticmethod
    def prepare_context_with_excerpt(context_data, agent_config, excerpt_field=None):
        """Extract focused context using excerpt as anchor"""
        excerpt_config = agent_config.get('excerpt_config', {})
        
        if excerpt_config.get('enabled') and excerpt_field:
            extractor = ExcerptContextExtractor(excerpt_config)
            focused_data = extractor.extract_context(
                full_text=context_data.get('page_content', ''),
                excerpt=context_data.get(excerpt_field, ''),
                metadata=context_data
            )
            context_data.update(focused_data)
            
        return apply_remove_collection(context_data, agent_config)
```

#### Transformation Stage
```python
# In transformation_stage.py
class ExcerptTransformationStage(BaseStage):
    def process(self, data: Any, context: PipelineContext) -> StageResult:
        """Apply excerpt-based context extraction"""
        excerpt_config = self.config.get('excerpt_config', {})
        
        if excerpt_config.get('enabled'):
            transformed_data = [
                self._extract_excerpt_context(record, excerpt_config)
                for record in data
            ]
            return StageResult(
                success=True,
                data=transformed_data,
                metadata={"transformation": "excerpt_extraction"}
            )
        
        return StageResult(success=True, data=data)
```

## Implementation Architecture

### Core Components

#### 1. ExcerptContextExtractor
```python
class ExcerptContextExtractor:
    """Main extraction engine"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.searcher = self._create_searcher()
        self.boundary_handler = self._create_boundary_handler()
    
    def extract_context(self, full_text: str, excerpt: str, metadata: Dict) -> Dict:
        """Extract context window around excerpt location"""
        
    def _find_excerpt_location(self, full_text: str, excerpt: str) -> Optional[MatchResult]:
        """Locate excerpt within full text"""
        
    def _extract_context_window(self, full_text: str, location: MatchResult) -> str:
        """Extract context around located excerpt"""
```

#### 2. Search Strategies
```python
class SearchStrategy(ABC):
    """Abstract base for search implementations"""
    @abstractmethod
    def find_match(self, full_text: str, excerpt: str) -> Optional[MatchResult]:
        pass

class ExactSearchStrategy(SearchStrategy):
    """Exact string matching"""
    
class RegexSearchStrategy(SearchStrategy):
    """Regular expression matching"""
    
class FuzzySearchStrategy(SearchStrategy):
    """Fuzzy string matching with configurable thresholds"""
    
class SemanticSearchStrategy(SearchStrategy):
    """Vector-based semantic similarity matching"""
```

#### 3. Boundary Handlers
```python
class BoundaryHandler(ABC):
    """Abstract base for boundary calculation"""
    @abstractmethod
    def calculate_boundaries(self, text: str, position: int, window_size: int) -> Tuple[int, int]:
        pass

class CharacterBoundaryHandler(BoundaryHandler):
    """Character-based boundary calculation"""
    
class TokenBoundaryHandler(BoundaryHandler):
    """Token-based boundary calculation"""
    
class SentenceBoundaryHandler(BoundaryHandler):
    """Sentence-aware boundary calculation"""
```

#### 4. Fallback Handlers
```python
class FallbackHandler(ABC):
    """Abstract base for fallback strategies"""
    @abstractmethod
    def handle_no_match(self, full_text: str, excerpt: str, config: Dict) -> Dict:
        pass

class FullContentFallback(FallbackHandler):
    """Return full content when excerpt not found"""
    
class ChunkingFallback(FallbackHandler):
    """Fall back to traditional chunking"""
    
class ErrorFallback(FallbackHandler):
    """Raise error when excerpt not found"""
```

## Performance Considerations

### Memory Usage
- **Context Windows**: Smaller windows = lower memory usage
- **Caching**: Search results can be cached for repeated excerpts
- **Streaming**: Large documents can be processed in streams

### Processing Speed
- **Search Algorithm Choice**: Exact > Regex > Fuzzy > Semantic (speed order)
- **Boundary Calculation**: Characters > Tokens > Sentences (speed order)
- **Preprocessing**: Normalize text once, reuse for multiple searches

### Scalability
- **Batch Processing**: Process multiple excerpts simultaneously
- **Parallel Processing**: Different documents can be processed in parallel
- **Index Building**: For repeated searches, build search indices

## Monitoring and Debugging

### Metrics to Track
```python
{
  "excerpt_extraction_metrics": {
    "total_extractions": 1000,
    "successful_matches": 950,
    "fallback_usage": 50,
    "average_context_size": 485,
    "search_mode_distribution": {
      "exact": 600,
      "fuzzy": 300,
      "regex": 50
    },
    "boundary_type_usage": {
      "characters": 700,
      "sentences": 250,
      "tokens": 50
    }
  }
}
```

### Debug Information
```python
{
  "debug_info": {
    "search_attempts": [
      {
        "method": "exact",
        "success": false,
        "reason": "no_exact_match"
      },
      {
        "method": "fuzzy",
        "success": true,
        "confidence": 0.87,
        "match_position": {"start": 1250, "end": 1285}
      }
    ],
    "context_extraction": {
      "original_position": {"start": 1250, "end": 1285},
      "context_bounds": {"start": 950, "end": 1585},
      "context_size": 635,
      "boundary_adjustments": "sentence_aligned"
    }
  }
}
```

## Error Handling

### Common Error Scenarios
1. **Excerpt Not Found**: Handle via fallback strategies
2. **Empty Context Window**: Expand window or use fallback
3. **Malformed Input**: Validate input data structure
4. **Processing Errors**: Log and continue with fallback

### Error Recovery
```python
{
  "error_handling": {
    "excerpt_not_found": "use_fallback_strategy",
    "empty_page_content": "skip_record",
    "invalid_excerpt": "log_and_skip",
    "context_extraction_failed": "use_full_content"
  }
}
```

## Migration Guide

### From Existing Chunking
1. **Identify Use Cases**: Determine which agents would benefit from excerpt-based extraction
2. **Configure Gradually**: Start with fallback to existing chunking
3. **Test Performance**: Compare accuracy and cost metrics
4. **Scale Up**: Gradually enable for more agents

### Backwards Compatibility
- **Default Disabled**: Feature is opt-in via configuration
- **Fallback Support**: Can fall back to existing chunking methods
- **Data Format**: Maintains existing data structure expectations

## Examples

### Example 1: Research Paper Analysis
```yaml
# Agent Configuration
- agent_type: ResearchAnalyzer
  excerpt_config:
    enabled: true
    search_mode: "fuzzy"
    fuzzy_threshold: 0.80
    context_window: 600
    boundary_type: "sentences"
    fallback_strategy: "chunking"
  side_collection:
    - paper_id
    - title
    - authors
    - excerpt
    - page_content
  prompt: $research.methodology_analysis
```

```python
# Input Data
{
  "paper_id": "arxiv_2024_001",
  "title": "Novel Approaches to Machine Learning",
  "excerpt": "Our methodology employs a hybrid approach combining reinforcement learning with transformer architectures",
  "page_content": "...full paper content...",
  "authors": ["Dr. Smith", "Dr. Johnson"]
}

# Processed Output
{
  "paper_id": "arxiv_2024_001",
  "title": "Novel Approaches to Machine Learning",
  "excerpt": "Our methodology employs a hybrid approach...",
  "focused_content": "In this section, we describe our experimental setup. Our methodology employs a hybrid approach combining reinforcement learning with transformer architectures, which allows for improved performance on complex tasks. The hybrid model consists of three main components: a transformer encoder for feature extraction, a reinforcement learning agent for decision making, and a feedback mechanism for continuous improvement.",
  "authors": ["Dr. Smith", "Dr. Johnson"],
  "context_metadata": {
    "match_confidence": 0.85,
    "context_size": 486,
    "sentences_included": 4
  }
}
```

### Example 2: Legal Document Processing
```yaml
# Agent Configuration
- agent_type: ContractAnalyzer
  excerpt_config:
    enabled: true
    search_mode: "exact"
    context_window: 1000
    boundary_type: "paragraphs"
    case_sensitive: false
  side_collection:
    - contract_id
    - clause_excerpt
    - full_contract
  remove_collection:
    - raw_text
  prompt: $legal.clause_analysis
```

### Example 3: Code Documentation
```yaml
# Agent Configuration
- agent_type: CodeDocumenter
  excerpt_config:
    enabled: true
    search_mode: "regex"
    context_window: 50  # lines of code
    boundary_type: "lines"
    fallback_strategy: "error"
  side_collection:
    - file_path
    - function_signature
    - source_code
  prompt: $code.documentation_generator
```

## Future Enhancements

### Planned Features
1. **Multi-Excerpt Support**: Handle multiple excerpts per document
2. **Hierarchical Context**: Extract nested context levels (paragraph → section → document)
3. **Smart Boundaries**: AI-powered boundary detection based on content type
4. **Cross-Document Linking**: Link related excerpts across multiple documents
5. **Visual Context**: Support for extracting context around images/tables
6. **Real-time Processing**: Support for streaming document processing

### Integration Possibilities
1. **Vector Databases**: Integration with vector stores for semantic search
2. **Knowledge Graphs**: Connect excerpts through knowledge graph relationships
3. **Citation Networks**: Track excerpt relationships across document collections
4. **Version Control**: Track excerpt changes across document versions

## Conclusion

Excerpt-based context extraction provides a powerful, configurable approach to precision text processing within the agent-actions framework. By focusing on semantically relevant content rather than mechanical chunking, it enables more accurate agent processing while significantly reducing costs and processing time. The feature integrates seamlessly with existing workflows while providing extensive configuration options for different use cases.