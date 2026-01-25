#!/usr/bin/env python3

import json
import numpy as np
from typing import List, Dict, Any, Tuple
from sentence_transformers import SentenceTransformer
from sklearn.cluster import KMeans, DBSCAN, AgglomerativeClustering
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import StandardScaler
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from collections import defaultdict, Counter
import re
import logging
import uuid
from agent_actions import udf_tool


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FinalGenericClustering:
    """
    Final robust clustering implementation for any JSON structure.
    """
    
    def __init__(self, model_name: str = 'sentence-transformers/all-MiniLM-L6-v2', use_gpu: bool = True):
        # GPU optimization like NeMo Curator
        import torch
        self.device = 'cuda' if use_gpu and torch.cuda.is_available() else 'cpu'
        self.model = SentenceTransformer(model_name, device=self.device)
        logger.info(f"Using device: {self.device} (NeMo Curator style)")
        
    def extract_all_text(self, obj: Any) -> str:
        """Extract all text from any JSON structure."""
        text_parts = []
        
        def recursive_extract(item):
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, (int, float, bool)):
                text_parts.append(str(item))
            elif isinstance(item, dict):
                for key, value in item.items():
                    if isinstance(key, str):
                        text_parts.append(key)
                    recursive_extract(value)
            elif isinstance(item, list):
                for element in item:
                    recursive_extract(element)
            elif item is not None:
                text_parts.append(str(item))
        
        recursive_extract(obj)
        return " ".join(text_parts)
    
    def create_features(self, objects: List[Dict[str, Any]]) -> np.ndarray:
        """Create feature matrix with proper dimension handling."""
        texts = [self.extract_all_text(obj) for obj in objects]
        
        # Primary: Semantic embeddings (NeMo Curator approach)
        semantic_embeddings = self.model.encode(texts, convert_to_tensor=True, device=self.device)
        
        # Convert to numpy if tensor (GPU compatibility)
        import torch
        if torch.is_tensor(semantic_embeddings):
            semantic_embeddings = semantic_embeddings.cpu().numpy()
            
        logger.info(f"Semantic embeddings shape: {semantic_embeddings.shape}")
        
        # Secondary: Simple structural features
        structural_features = []
        for obj in objects:
            features = [
                len(str(obj)),  # JSON length
                str(obj).count('{'),  # Object count
                str(obj).count('['),  # Array count
                len(re.findall(r'\d+', str(obj))),  # Number count
                len(self.extract_all_text(obj).split()),  # Word count
                str(obj).count('"'),  # String count
                str(obj).count(':'),  # Key-value pairs
                len([c for c in str(obj) if c.isupper()]),  # Uppercase letters
            ]
            structural_features.append(features)
        
        structural_matrix = np.array(structural_features, dtype=float)
        logger.info(f"Structural features shape: {structural_matrix.shape}")
        
        # Normalize both feature types
        scaler = StandardScaler()
        semantic_norm = scaler.fit_transform(semantic_embeddings)
        
        if structural_matrix.shape[0] > 0 and structural_matrix.shape[1] > 0:
            structural_norm = scaler.fit_transform(structural_matrix)
        else:
            structural_norm = np.zeros((len(objects), 8))
        
        # Combine with weighted approach - keep dimensions manageable
        # Use only semantic embeddings if we have few samples
        if len(objects) < 10:
            logger.info("Using semantic embeddings only (small dataset)")
            return semantic_norm
        else:
            # For larger datasets, combine features
            # Reduce semantic dimensions if too large
            if semantic_norm.shape[1] > 100:
                from sklearn.decomposition import PCA
                n_components = min(50, len(objects) - 1)  # Ensure valid PCA
                pca = PCA(n_components=n_components)
                semantic_reduced = pca.fit_transform(semantic_norm)
                logger.info(f"Reduced semantic dimensions to {semantic_reduced.shape[1]}")
            else:
                semantic_reduced = semantic_norm
            
            # Combine features
            combined = np.concatenate([semantic_reduced, structural_norm], axis=1)
            logger.info(f"Combined features shape: {combined.shape}")
            return combined
    
    def nemo_style_clustering(self, features: np.ndarray, objects: List[Dict[str, Any]]) -> Tuple[np.ndarray, Dict]:
        """
        NeMo Curator style clustering with k-means and centroid selection.
        """
        n_samples, n_features = features.shape
        logger.info(f"Clustering {n_samples} samples with {n_features} features")
        
        # Determine optimal number of clusters
        if n_samples <= 2:
            # Too few samples
            labels = np.arange(n_samples)
            return labels, {'method': 'individual', 'reason': 'too_few_samples'}
        
        # NeMo Curator approach: Use k-means as primary method
        min_clusters = 2
        max_clusters = min(max(2, n_samples // 2), 6)
        
        best_result = None
        best_score = -1
        
        # Prioritize k-means like NeMo Curator
        
        # Try different methods
        methods = []
        
        # K-means with different k values
        for k in range(min_clusters, max_clusters + 1):
            try:
                kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
                labels = kmeans.fit_predict(features)
                
                # Calculate quality score
                try:
                    silhouette = silhouette_score(features, labels)
                except:
                    silhouette = 0
                
                # Balance score
                cluster_sizes = Counter(labels)
                sizes = list(cluster_sizes.values())
                balance = 1 - (np.std(sizes) / np.mean(sizes)) if np.mean(sizes) > 0 else 0
                
                # Combined score
                score = 0.7 * silhouette + 0.3 * balance
                
                methods.append({
                    'method': f'kmeans_{k}',
                    'labels': labels,
                    'score': score,
                    'silhouette': silhouette,
                    'balance': balance,
                    'n_clusters': k
                })
                
            except Exception as e:
                logger.warning(f"K-means k={k} failed: {e}")
        
        # Agglomerative clustering
        for k in range(min_clusters, max_clusters + 1):
            try:
                agg = AgglomerativeClustering(n_clusters=k, linkage='ward')
                labels = agg.fit_predict(features)
                
                try:
                    silhouette = silhouette_score(features, labels)
                except:
                    silhouette = 0
                
                cluster_sizes = Counter(labels)
                sizes = list(cluster_sizes.values())
                balance = 1 - (np.std(sizes) / np.mean(sizes)) if np.mean(sizes) > 0 else 0
                score = 0.7 * silhouette + 0.3 * balance
                
                methods.append({
                    'method': f'agglom_{k}',
                    'labels': labels,
                    'score': score,
                    'silhouette': silhouette,
                    'balance': balance,
                    'n_clusters': k
                })
                
            except Exception as e:
                logger.warning(f"Agglomerative k={k} failed: {e}")
        
        # DBSCAN
        for eps in [0.3, 0.5, 0.8]:
            try:
                dbscan = DBSCAN(eps=eps, min_samples=max(1, n_samples // 4))
                labels = dbscan.fit_predict(features)
                n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
                
                if 1 < n_clusters < n_samples:
                    try:
                        silhouette = silhouette_score(features, labels)
                    except:
                        silhouette = 0
                    
                    cluster_sizes = Counter([l for l in labels if l != -1])
                    if cluster_sizes:
                        sizes = list(cluster_sizes.values())
                        balance = 1 - (np.std(sizes) / np.mean(sizes)) if np.mean(sizes) > 0 else 0
                        score = 0.7 * silhouette + 0.3 * balance
                        
                        methods.append({
                            'method': f'dbscan_{eps}',
                            'labels': labels,
                            'score': score,
                            'silhouette': silhouette,
                            'balance': balance,
                            'n_clusters': n_clusters
                        })
                
            except Exception as e:
                logger.warning(f"DBSCAN eps={eps} failed: {e}")
        
        # Select best method
        if methods:
            best_result = max(methods, key=lambda x: x['score'])
            logger.info(f"Best method: {best_result['method']} (score: {best_result['score']:.3f})")
            return best_result['labels'], {
                'method': best_result['method'],
                'score': best_result['score'],
                'silhouette': best_result['silhouette'],
                'balance': best_result['balance'],
                'n_clusters': best_result['n_clusters'],
                'alternatives': len(methods)
            }
        else:
            # Fallback
            logger.warning("All methods failed, using binary clustering")
            labels = np.array([i % 2 for i in range(n_samples)])
            return labels, {'method': 'fallback_binary', 'reason': 'all_methods_failed'}
    
    def find_centroid_representatives(self, features: np.ndarray, labels: np.ndarray, 
                                     cluster_centers: np.ndarray) -> Dict[int, int]:
        """
        NeMo Curator style: Find items closest to cluster centroids as representatives.
        """
        representatives = {}
        
        for cluster_id in np.unique(labels):
            if cluster_id == -1:  # Skip noise
                continue
                
            cluster_mask = labels == cluster_id
            cluster_indices = np.where(cluster_mask)[0]
            cluster_points = features[cluster_mask]
            
            if len(cluster_indices) == 0:
                continue
                
            if len(cluster_indices) == 1:
                representatives[cluster_id] = cluster_indices[0]
                continue
            
            # Find point closest to centroid (NeMo Curator approach)
            if cluster_id < len(cluster_centers):
                centroid = cluster_centers[cluster_id]
                distances = np.linalg.norm(cluster_points - centroid, axis=1)
                closest_idx = np.argmin(distances)
                representatives[cluster_id] = cluster_indices[closest_idx]
            else:
                # Fallback: use first item
                representatives[cluster_id] = cluster_indices[0]
        
        return representatives
    
    def analyze_clusters(self, objects: List[Dict[str, Any]], labels: np.ndarray) -> Dict:
        """Analyze cluster characteristics."""
        analysis = {}
        
        for cluster_id in np.unique(labels):
            if cluster_id == -1:  # Skip noise
                continue
            
            cluster_objects = [objects[i] for i, label in enumerate(labels) if label == cluster_id]
            cluster_texts = [self.extract_all_text(obj) for obj in cluster_objects]
            
            # Common words analysis
            all_words = []
            for text in cluster_texts:
                all_words.extend(text.lower().split())
            
            word_counts = Counter(all_words)
            common_words = [word for word, count in word_counts.most_common(5) 
                          if len(word) > 2 and word.isalpha()]
            
            # Structural patterns
            avg_length = np.mean([len(str(obj)) for obj in cluster_objects])
            
            analysis[cluster_id] = {
                'size': len(cluster_objects),
                'common_words': common_words[:3],
                'avg_json_length': avg_length,
                'sample_fields': list(cluster_objects[0].keys()) if cluster_objects else []
            }
        
        return analysis

def final_clustering(objects: List[Dict[str, Any]], 
                    analyze: bool = True) -> Dict[str, Any]:
    """
    Final clustering implementation that works with any JSON.
    """
    if not objects:
        return {
            'objects': [],
            'clusters': {},
            'method': 'empty',
            'num_clusters': 0
        }
    
    clusterer = FinalGenericClustering()
    
    try:
        # Create features
        features = clusterer.create_features(objects)
        
        # Apply NeMo Curator style clustering
        labels, cluster_info = clusterer.nemo_style_clustering(features, objects)
        
        # Create enhanced objects
        clustered_objects = []
        for i, obj in enumerate(objects):
            enhanced_obj = obj.copy()
            enhanced_obj['cluster_id'] = int(labels[i])
            guid = uuid.uuid4().hex[:8]
            enhanced_obj['cluster_tag'] = f"cluster_{labels[i]}_{guid}"
            clustered_objects.append(enhanced_obj)
        
        # Group by clusters
        clusters = defaultdict(list)
        for obj in clustered_objects:
            clusters[obj['cluster_id']].append(obj)
        
        result = {
            'objects': clustered_objects,
            'clusters': dict(clusters),
            'cluster_info': cluster_info,
            'num_clusters': len(clusters),
            'feature_dimensions': features.shape[1] if features.size > 0 else 0
        }
        
        # Add analysis if requested
        if analyze:
            analysis = clusterer.analyze_clusters(objects, labels)
            result['cluster_analysis'] = analysis
        
        return result
        
    except Exception as e:
        logger.error(f"Clustering failed: {e}")
        import traceback
        traceback.print_exc()
        
        # Return fallback
        fallback_objects = []
        for i, obj in enumerate(objects):
            enhanced_obj = obj.copy()
            enhanced_obj['cluster_id'] = 0
            enhanced_obj['cluster_tag'] = "cluster_0"
            fallback_objects.append(enhanced_obj)
        
        return {
            'objects': fallback_objects,
            'clusters': {0: fallback_objects},
            'method': 'error_fallback',
            'num_clusters': 1,
            'error': str(e)
        }

def demonstrate_clustering(json_file: str):
    """Demonstrate clustering capabilities."""
    
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    print(f"🚀 FINAL CLUSTERING DEMONSTRATION")
    print(f"📊 Dataset: {len(data)} objects from {json_file}")
    print("=" * 70)
    
    # Run clustering
    result = final_clustering(data, analyze=True)
    
    if 'error' in result:
        print(f"❌ Error: {result['error']}")
        return
    
    print(f"✅ Clustering successful!")
    print(f"🎯 Method: {result['cluster_info']['method']}")
    print(f"📈 Quality score: {result['cluster_info'].get('score', 'N/A'):.3f}")
    print(f"🔢 Feature dimensions: {result['feature_dimensions']}")
    print(f"🏷️ Clusters found: {result['num_clusters']}")
    
    # Show cluster details
    print(f"\n📋 CLUSTER ANALYSIS")
    print("-" * 50)
    
    clusters = result['clusters']
    analysis = result.get('cluster_analysis', {})
    
    for cluster_id in sorted(clusters.keys()):
        items = clusters[cluster_id]
        cluster_analysis = analysis.get(cluster_id, {})
        
        print(f"\n🏷️  Cluster {cluster_id}: {len(items)} items")
        
        if cluster_analysis:
            print(f"   Common words: {cluster_analysis.get('common_words', [])}")
            print(f"   Avg JSON length: {cluster_analysis.get('avg_json_length', 0):.0f}")
            print(f"   Sample fields: {cluster_analysis.get('sample_fields', [])[:3]}")
        
        # Show sample items
        for i, item in enumerate(items[:2]):  # Show up to 2 samples
            sample_text = ""
            for key, value in item.items():
                if key not in ['cluster_id', 'cluster_tag'] and sample_text == "":
                    sample_text = str(value)[:60] + ("..." if len(str(value)) > 60 else "")
                    break
            print(f"     Sample {i+1}: {sample_text}")
    
    # Save results
    output_file = json_file.replace('.json', '_final_clustered.json')
    with open(output_file, 'w') as f:
        json.dump(result['objects'], f, indent=2)
    
    print(f"\n💾 Results saved to: {output_file}")
    print(f"🎉 Clustering complete! Any JSON structure supported.")







@udf_tool()
def cluster_list(data):
    """
    Simple function that takes a list and returns a clustered list.

    Args:
        data: Dictionary with 'candidate_facts_list' field containing list to cluster

    Returns:
        List of dictionaries with added cluster_id and cluster_tag fields
    """
    # Handle content wrapper
    if 'content' in data:
        content = data['content']
    else:
        content = data

    input_list = content.get('candidate_facts_list', [])
    if not input_list:
        return []

    result = final_clustering(input_list)
    return result['objects']

def cluster_list_with_info(input_list):
    """
    Enhanced function that returns both clustered list and cluster information.
    
    Args:
        input_list: List of dictionaries (any JSON structure)
        
    Returns:
        dict: {
            'clustered_list': list with cluster tags,
            'num_clusters': int,
            'cluster_info': dict with method details,
            'clusters_grouped': dict with items grouped by cluster_id
        }
    """
    result = final_clustering(input_list)
    
    return[ {
        'clustered_list': result['objects'],
        'num_clusters': result['num_clusters'],
        'cluster_info': result['cluster_info'],
        'clusters_grouped': result['clusters']
    }]





if __name__ == "__main__":
    test_file = "/Users/muizz/Documents/codeshop/qanalabs/qanalabs_exam_item_filter/test.json"
    demonstrate_clustering(test_file)