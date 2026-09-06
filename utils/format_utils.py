import re
import numpy
import struct
import math
import numpy

from .tbn_codec import TBNCodec


# This used to catch any exception in run time and raise it to blender output console.
class Fatal(Exception):
    pass


class FormatUtils:
    f32_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]32)+_FLOAT''')
    f16_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]16)+_FLOAT''')
    u32_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]32)+_UINT''')
    u16_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]16)+_UINT''')
    u8_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]8)+_UINT''')
    s32_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]32)+_SINT''')
    s16_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]16)+_SINT''')
    s8_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]8)+_SINT''')
    unorm16_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]16)+_UNORM''')
    unorm8_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]8)+_UNORM''')
    snorm16_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]16)+_SNORM''')
    snorm8_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD]8)+_SNORM''')

    misc_float_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD][0-9]+)+_(?:FLOAT|UNORM|SNORM)''')
    misc_int_pattern = re.compile(r'''(?:DXGI_FORMAT_)?(?:[RGBAD][0-9]+)+_[SU]INT''')

    components_pattern = re.compile(r'''(?<![0-9])[0-9]+(?![0-9])''')

    @classmethod
    def get_nptype_from_format(cls,fmt):
        '''
        Parse a DXGI format string and return the corresponding numpy data type.
        '''
        if cls.f32_pattern.match(fmt):
            return numpy.float32
        elif cls.f16_pattern.match(fmt):
            return numpy.float16
        elif cls.u32_pattern.match(fmt):
            return numpy.uint32
        elif cls.u16_pattern.match(fmt):
            return numpy.uint16
        elif cls.u8_pattern.match(fmt):
            return numpy.uint8
        elif cls.s32_pattern.match(fmt):
            return numpy.int32
        elif cls.s16_pattern.match(fmt):
            return numpy.int16
        elif cls.s8_pattern.match(fmt):
            return numpy.int8

        elif cls.unorm16_pattern.match(fmt):
            return numpy.uint16
        elif cls.unorm8_pattern.match(fmt):
            return numpy.uint8
        elif cls.snorm16_pattern.match(fmt):
            return numpy.int16
        elif cls.snorm8_pattern.match(fmt):
            return numpy.int8

        raise Fatal('Mesh uses an unsupported DXGI Format: %s' % fmt)

    @classmethod
    def EncoderDecoder(cls,fmt):
        '''
        This conversion is extremely inefficient and not recommended.
        When possible, use numpy's astype method instead.

        Honestly, this conversion layer cannot be skipped; without it the data would be wrong.
        '''
        if cls.f32_pattern.match(fmt):
            return (lambda data: b''.join(struct.pack('<f', x) for x in data),
                    lambda data: numpy.frombuffer(data, numpy.float32).tolist())
        if cls.f16_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.float16).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.float16).tolist())
        if cls.u32_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.uint32).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.uint32).tolist())
        if cls.u16_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.uint16).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.uint16).tolist())
        if cls.u8_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.uint8).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.uint8).tolist())
        if cls.s32_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.int32).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.int32).tolist())
        if cls.s16_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.int16).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.int16).tolist())
        if cls.s8_pattern.match(fmt):
            return (lambda data: numpy.fromiter(data, numpy.int8).tobytes(),
                    lambda data: numpy.frombuffer(data, numpy.int8).tolist())

        if cls.unorm16_pattern.match(fmt):
            return (
                lambda data: numpy.around((numpy.fromiter(data, numpy.float32) * 65535.0)).astype(numpy.uint16).tobytes(),
                lambda data: (numpy.frombuffer(data, numpy.uint16) / 65535.0).tolist())
        if cls.unorm8_pattern.match(fmt):
            return (lambda data: numpy.around((numpy.fromiter(data, numpy.float32) * 255.0)).astype(numpy.uint8).tobytes(),
                    lambda data: (numpy.frombuffer(data, numpy.uint8) / 255.0).tolist())
        if cls.snorm16_pattern.match(fmt):
            return (
                lambda data: numpy.around((numpy.fromiter(data, numpy.float32) * 32767.0)).astype(numpy.int16).tobytes(),
                lambda data: (numpy.frombuffer(data, numpy.int16) / 32767.0).tolist())
        if cls.snorm8_pattern.match(fmt):
            return (lambda data: numpy.around((numpy.fromiter(data, numpy.float32) * 127.0)).astype(numpy.int8).tobytes(),
                    lambda data: (numpy.frombuffer(data, numpy.int8) / 127.0).tolist())
        # print(fmt)
        raise Fatal('File uses an unsupported DXGI Format: %s' % fmt)
    
    @classmethod
    def apply_format_conversion(cls, data, fmt):
        '''
        Importing from the given format requires the conversion; otherwise precision is lost.
        '''
        if cls.unorm16_pattern.match(fmt):
            decode_func = lambda x: (x / 65535.0).astype(numpy.float32)
        elif cls.unorm8_pattern.match(fmt):
            decode_func = lambda x: (x / 255.0).astype(numpy.float32)
        elif cls.snorm16_pattern.match(fmt):
            decode_func = lambda x: (x / 32767.0).astype(numpy.float32)
        elif cls.snorm8_pattern.match(fmt):
            decode_func = lambda x: (x / 127.0).astype(numpy.float32)
        else:
            return data  # If the format is none of the four above, return the raw data as-is

        # Apply the conversion to the input data
        decoded_data = decode_func(data)
        return decoded_data

    @classmethod
    def format_size(cls,fmt):
        '''
        Given a FORMAT, return its size in bytes
        For example, given R32G32B32_FLOAT, return the size in bytes: 12

        XXX Note: the result here is not reliable. The correct ByteWidth should be defined in the data type rather than by calling this; this only keeps compatibility with fmt files from legacy architectures.
        This will be removed in the future, but it may keep existing for quite a long time.
        '''
        matches = cls.components_pattern.findall(fmt)
        return sum(map(int, matches)) // 8


    '''
    Utilities for various binary data format conversions
    '''
    # Vector normalization
    @staticmethod
    def vector_normalize(v):
        """Normalize a vector"""
        length = math.sqrt(sum(x * x for x in v))
        if length == 0:
            return v  # Avoid division by zero
        return [x / length for x in v]
    
    @classmethod
    def add_and_normalize_vectors(cls,v1, v2):
        """Add two vectors and normalize the result"""
        # Add the two vectors
        result = [a + b for a, b in zip(v1, v2)]
        # Normalize
        normalized_result = cls.vector_normalize(result)
        return normalized_result
    
    # Helper function: compute the dot product of two vectors
    @staticmethod
    def dot_product(v1, v2):
        return sum(a * b for a, b in zip(v1, v2))


    @staticmethod
    def convert_2x_float32_to_r16g16_unorm(input_array):
        """
        Quantize float32 values in [0, 1] with shape=(...,2)
        into uint16 [0,65535] and return a uint16 array with the same shape.
        A 1D input is also quantized element by element.
        """
        # Copy first to avoid modifying in place
        arr = numpy.asarray(input_array, dtype=numpy.float32)
        # Clamp to [0,1]
        numpy.clip(arr, 0.0, 1.0, out=arr)
        # Quantize: 65535 is the maximum value of R16G16_UNORM
        return numpy.round(arr * 65535).astype(numpy.uint16)

    '''
    These four UNORM/SNORM formats are special and need this handling; other float types can simply be converted with astype
    '''
    # @classmethod
    # def convert_4x_float32_to_r8g8b8a8_snorm(cls, input_array):
    #     return numpy.round(input_array * 127).astype(numpy.int8)

    @staticmethod
    def convert_4x_float32_to_r8g8b8a8_snorm(input_array):
        '''
        Rewritten following DeepSeek's suggestion; this may avoid certain problems
        '''
        arr = numpy.asarray(input_array, dtype=numpy.float32)
        # 1. Clamp to [-1, 1]
        numpy.clip(arr, -1.0, 1.0, out=arr)
        # 2. Quantize to [-127, 127]
        arr = numpy.round(arr * 127).astype(numpy.int8)
        # 3. Ensure -128 never appears (theoretically impossible after clip+round, but keep the extra safeguard)
        #    Actually this can be omitted, because -1.0*-127=127 and 1.0*127=127, which never reaches -128
        return arr

    @staticmethod
    def convert_4x_float32_to_r8g8b8a8_unorm(input_array):
        return numpy.round(input_array * 255).astype(numpy.uint8)
    
    @staticmethod
    def convert_4x_float32_to_r16g16b16a16_snorm(input_array):
        return numpy.round(input_array * 32767).astype(numpy.int16)
    
    @staticmethod
    def convert_4x_float32_to_r16g16b16a16_unorm(input_array):
        return numpy.round(input_array * 65535).astype(numpy.uint16)
    
    @staticmethod
    def convert_4x_float32_to_r16g16b16a16_snorm(input_array):
        return numpy.round(input_array * 32767).astype(numpy.int16)
   

    @staticmethod    
    def convert_4x_float32_to_r8g8b8a8_unorm_blendweights(input_array):
        # Ensure the input array is a float type
        # input_array_float = input_array.astype(numpy.float32)
    
        # Create the result array
        result = numpy.zeros_like(input_array, dtype=numpy.uint8)
        
        # Handle NaN values
        nan_mask = numpy.isnan(input_array).any(axis=1)
        valid_mask = ~nan_mask
        
        # Only process non-NaN rows
        valid_input = input_array[valid_mask]
        if valid_input.size == 0:
            return result
        
        # Compute the sum of each row
        row_sums = valid_input.sum(axis=1, keepdims=True)
        
        # Handle rows with a zero sum
        zero_sum_mask = (row_sums[:, 0] == 0)
        non_zero_mask = ~zero_sum_mask
        
        # Normalize weights
        normalized = numpy.zeros_like(valid_input)
        normalized[non_zero_mask] = valid_input[non_zero_mask] / row_sums[non_zero_mask] * 255.0
        
        # Compute the integer part and the fractional part
        int_part = numpy.floor(normalized).astype(numpy.int32)
        fractional = normalized - int_part
        
        # Set weights smaller than 1 to 0
        small_weight_mask = (normalized < 1) & non_zero_mask[:, numpy.newaxis]
        int_part[small_weight_mask] = 0
        fractional[small_weight_mask] = 0
        
        # Compute the precision error
        precision_error = 255 - int_part.sum(axis=1)
        
        # Compute tickets
        tickets = numpy.zeros_like(normalized)
        with numpy.errstate(divide='ignore', invalid='ignore'):
            tickets[non_zero_mask] = numpy.where(
                (normalized[non_zero_mask] >= 1) & (fractional[non_zero_mask] > 0),
                255 * fractional[non_zero_mask] / normalized[non_zero_mask],
                0
            )
        
        # Distribute the precision error
        output = int_part.copy()
        for i in range(precision_error.max()):
            # Find the rows that still need allocation
            need_allocation = (precision_error > 0)
            if not numpy.any(need_allocation):
                break
            
            # Find the position with the largest ticket in the current rows
            max_ticket_mask = numpy.zeros_like(tickets, dtype=bool)
            rows = numpy.where(need_allocation)[0]
            
            # For rows that have tickets
            has_ticket = (tickets[rows] > 0).any(axis=1)
            if numpy.any(has_ticket):
                ticket_rows = rows[has_ticket]
                row_indices = ticket_rows[:, numpy.newaxis]
                col_indices = tickets[ticket_rows].argmax(axis=1)
                max_ticket_mask[ticket_rows, col_indices] = True
                tickets[ticket_rows, col_indices] = 0
            
            # For rows without tickets
            no_ticket = ~has_ticket & need_allocation[rows]
            if numpy.any(no_ticket):
                no_ticket_rows = rows[no_ticket]
                # Find the position with the largest current weight
                max_weight_mask = numpy.zeros_like(tickets, dtype=bool)
                row_indices = no_ticket_rows[:, numpy.newaxis]
                col_indices = output[no_ticket_rows].argmax(axis=1)
                max_weight_mask[no_ticket_rows, col_indices] = True
                max_ticket_mask |= max_weight_mask
            
            # Apply the allocation
            output[max_ticket_mask] += 1
            precision_error[need_allocation] -= 1
        
        # Store the result back
        result[valid_mask] = output.astype(numpy.uint8)
        return result
    
    @staticmethod
    def convert_4x_float32_to_r8g8b8a8_unorm_blendweights_bk2(input_array):

        result = numpy.zeros_like(input_array, dtype=numpy.uint8)

        for i in range(input_array.shape[0]):
            weights = input_array[i]

            # If the weights contain NaN values, set all values of this row to 0.
            # Once weights have been painted, they never contain NaN values.
            find_nan = False
            for w in weights:
                if math.isnan(w):
                    row_normalized = [0, 0, 0, 0]
                    result[i] = numpy.array(row_normalized, dtype=numpy.uint8)
                    find_nan = True
                    break
                    # print(weights)
                    # raise Fatal("NaN found in weights")
            if find_nan:
                continue
            
            total = sum(weights)
            if total == 0:
                row_normalized = [0] * len(weights)
                result[i] = numpy.array(row_normalized, dtype=numpy.uint8)
                continue

            precision_error = 255

            tickets = [0] * len(weights)
            normalized_weights = [0] * len(weights)

            for index, weight in enumerate(weights):
                # Ignore zero weight
                if weight == 0:
                    continue

                weight = weight / total * 255
                # Ignore weight below minimal precision (1/255)
                if weight < 1:
                    normalized_weights[index] = 0
                    continue

                # Strip float part from the weight
                int_weight = 0

                int_weight = int(weight)

                normalized_weights[index] = int_weight
                # Reduce precision_error by the integer weight value
                precision_error -= int_weight
                # Calculate weight 'significance' index to prioritize lower weights with float loss
                tickets[index] = 255 / weight * (weight - int_weight)

            while precision_error > 0:
                ticket = max(tickets)
                if ticket > 0:
                    # Route `1` from precision_error to weights with non-zero ticket value first
                    idx = tickets.index(ticket)
                    tickets[idx] = 0
                else:
                    # Route remaining precision_error to highest weight to reduce its impact
                    idx = normalized_weights.index(max(normalized_weights))
                # Distribute `1` from precision_error
                normalized_weights[idx] += 1
                precision_error -= 1

            row_normalized = normalized_weights
            result[i] = numpy.array(row_normalized, dtype=numpy.uint8)
        return result


