/* carglint driver probe -- dispatch the EMITTED glint arithmetic on a real
 * device and hand the results back for comparison against dev/glint_model.py.
 *
 * argv[1] = kernel .spv (created through vkCreateShaderModule; when the layer
 *           is active this is the PLACEHOLDER and the layer swaps in the real
 *           kernel, which is the point -- the bytes that run are the served
 *           bytes)
 * argv[2] = input  .bin  (N * 16 float32)
 * argv[3] = output .bin  (N * 4  float32, written here)
 * argv[4] = N
 * argv[5..] = extra .spv files handed to vkCreateShaderModule only (the real
 *           ~300 KB patched raygens)
 */
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t *slurp(const char *p, size_t *n) {
    FILE *f = fopen(p, "rb"); if (!f) { perror(p); exit(3); }
    fseek(f, 0, SEEK_END); long s = ftell(f); fseek(f, 0, SEEK_SET);
    uint32_t *b = malloc(s ? s : 4);
    if (fread(b, 1, s, f) != (size_t)s) { perror(p); exit(3); }
    fclose(f); *n = s; return b;
}
#define CK(x,m) do{VkResult _r=(x); if(_r!=VK_SUCCESS){printf("FAIL %s -> %d\n",m,_r);return 4;}}while(0)

static uint32_t mtype(VkPhysicalDevice pd, uint32_t bits, VkMemoryPropertyFlags want) {
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    for (uint32_t i = 0; i < mp.memoryTypeCount; i++)
        if ((bits & (1u << i)) && (mp.memoryTypes[i].propertyFlags & want) == want) return i;
    return ~0u;
}

int main(int argc, char **argv) {
    if (argc < 5) { printf("usage: probe kernel.spv in.bin out.bin N [extra.spv...]\n"); return 2; }
    uint32_t N = (uint32_t)strtoul(argv[4], NULL, 10);

    VkApplicationInfo ai = { VK_STRUCTURE_TYPE_APPLICATION_INFO };
    ai.pApplicationName = "carglint-probe"; ai.apiVersion = VK_API_VERSION_1_3;
    VkInstanceCreateInfo ici = { VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO };
    ici.pApplicationInfo = &ai;
    VkInstance inst; CK(vkCreateInstance(&ici, NULL, &inst), "vkCreateInstance");
    uint32_t np = 0; vkEnumeratePhysicalDevices(inst, &np, NULL);
    if (!np) { printf("FAIL no physical device\n"); return 4; }
    VkPhysicalDevice *pds = malloc(np * sizeof *pds);
    vkEnumeratePhysicalDevices(inst, &np, pds);
    VkPhysicalDevice pd = pds[0];
    VkPhysicalDeviceProperties props; vkGetPhysicalDeviceProperties(pd, &props);
    printf("device: %s\n", props.deviceName);

    uint32_t nq = 0; vkGetPhysicalDeviceQueueFamilyProperties(pd, &nq, NULL);
    VkQueueFamilyProperties *qs = malloc(nq * sizeof *qs);
    vkGetPhysicalDeviceQueueFamilyProperties(pd, &nq, qs);
    uint32_t qf = ~0u;
    for (uint32_t i = 0; i < nq; i++) if (qs[i].queueFlags & VK_QUEUE_COMPUTE_BIT) { qf = i; break; }
    if (qf == ~0u) { printf("FAIL no compute queue\n"); return 4; }
    float pri = 1.0f;
    VkDeviceQueueCreateInfo qci = { VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO };
    qci.queueFamilyIndex = qf; qci.queueCount = 1; qci.pQueuePriorities = &pri;
    VkDeviceCreateInfo dci = { VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO };
    dci.queueCreateInfoCount = 1; dci.pQueueCreateInfos = &qci;
    VkDevice dev; CK(vkCreateDevice(pd, &dci, NULL, &dev), "vkCreateDevice");
    VkQueue q; vkGetDeviceQueue(dev, qf, 0, &q);

    /* two host-visible storage buffers */
    VkDeviceSize szin = (VkDeviceSize)N * 16 * 4, szout = (VkDeviceSize)N * 4;
    VkBuffer buf[2]; VkDeviceMemory mem[2]; void *map[2];
    VkDeviceSize sz[2] = { szin, szout };
    for (int i = 0; i < 2; i++) {
        VkBufferCreateInfo bi = { VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO };
        bi.size = sz[i]; bi.usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT;
        bi.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
        CK(vkCreateBuffer(dev, &bi, NULL, &buf[i]), "vkCreateBuffer");
        VkMemoryRequirements mr; vkGetBufferMemoryRequirements(dev, buf[i], &mr);
        uint32_t t = mtype(pd, mr.memoryTypeBits,
                           VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        if (t == ~0u) { printf("FAIL no host-visible memory\n"); return 4; }
        VkMemoryAllocateInfo mai = { VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO };
        mai.allocationSize = mr.size; mai.memoryTypeIndex = t;
        CK(vkAllocateMemory(dev, &mai, NULL, &mem[i]), "vkAllocateMemory");
        CK(vkBindBufferMemory(dev, buf[i], mem[i], 0), "vkBindBufferMemory");
        CK(vkMapMemory(dev, mem[i], 0, sz[i], 0, &map[i]), "vkMapMemory");
    }
    { size_t n; uint32_t *in = slurp(argv[2], &n);
      if (n != szin) { printf("FAIL input is %zu B, want %llu\n", n, (unsigned long long)szin); return 4; }
      memcpy(map[0], in, n); free(in); }
    memset(map[1], 0xff, szout);

    VkDescriptorSetLayoutBinding b[2] = {
        { 0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL },
        { 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL } };
    VkDescriptorSetLayoutCreateInfo dli = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO };
    dli.bindingCount = 2; dli.pBindings = b;
    VkDescriptorSetLayout dsl; CK(vkCreateDescriptorSetLayout(dev, &dli, NULL, &dsl), "dsl");
    VkPipelineLayoutCreateInfo pli = { VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO };
    pli.setLayoutCount = 1; pli.pSetLayouts = &dsl;
    VkPipelineLayout pl; CK(vkCreatePipelineLayout(dev, &pli, NULL, &pl), "pl");

    size_t kn; uint32_t *kb = slurp(argv[1], &kn);
    VkShaderModuleCreateInfo smi = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
    smi.codeSize = kn; smi.pCode = kb;
    VkShaderModule sm; VkResult r = vkCreateShaderModule(dev, &smi, NULL, &sm);
    printf("vkCreateShaderModule(kernel, %zu B) -> %d\n", kn, r);
    if (r != VK_SUCCESS) return 4;
    VkComputePipelineCreateInfo cpi = { VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO };
    cpi.stage.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    cpi.stage.stage = VK_SHADER_STAGE_COMPUTE_BIT; cpi.stage.module = sm;
    cpi.stage.pName = "main"; cpi.layout = pl;
    VkPipeline pipe;
    r = vkCreateComputePipelines(dev, VK_NULL_HANDLE, 1, &cpi, NULL, &pipe);
    printf("vkCreateComputePipelines -> %d\n", r);
    if (r != VK_SUCCESS) return 4;

    VkDescriptorPoolSize ps = { VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2 };
    VkDescriptorPoolCreateInfo dpi = { VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO };
    dpi.maxSets = 1; dpi.poolSizeCount = 1; dpi.pPoolSizes = &ps;
    VkDescriptorPool dp; CK(vkCreateDescriptorPool(dev, &dpi, NULL, &dp), "dp");
    VkDescriptorSetAllocateInfo dsi = { VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO };
    dsi.descriptorPool = dp; dsi.descriptorSetCount = 1; dsi.pSetLayouts = &dsl;
    VkDescriptorSet ds; CK(vkAllocateDescriptorSets(dev, &dsi, &ds), "ds");
    VkDescriptorBufferInfo bi0 = { buf[0], 0, szin }, bi1 = { buf[1], 0, szout };
    VkWriteDescriptorSet w[2] = {
        { VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, ds, 0, 0, 1,
          VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi0, NULL },
        { VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, ds, 1, 0, 1,
          VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi1, NULL } };
    vkUpdateDescriptorSets(dev, 2, w, 0, NULL);

    VkCommandPoolCreateInfo cpci = { VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO };
    cpci.queueFamilyIndex = qf;
    VkCommandPool cp; CK(vkCreateCommandPool(dev, &cpci, NULL, &cp), "cp");
    VkCommandBufferAllocateInfo cbi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO };
    cbi.commandPool = cp; cbi.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY; cbi.commandBufferCount = 1;
    VkCommandBuffer cb; CK(vkAllocateCommandBuffers(dev, &cbi, &cb), "cb");
    VkCommandBufferBeginInfo bbi = { VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO };
    bbi.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
    CK(vkBeginCommandBuffer(cb, &bbi), "begin");
    vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pipe);
    vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &ds, 0, NULL);
    vkCmdDispatch(cb, (N + 63) / 64, 1, 1);
    CK(vkEndCommandBuffer(cb), "end");
    VkSubmitInfo si = { VK_STRUCTURE_TYPE_SUBMIT_INFO };
    si.commandBufferCount = 1; si.pCommandBuffers = &cb;
    CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE), "submit");
    CK(vkQueueWaitIdle(q), "waitidle");

    FILE *f = fopen(argv[3], "wb");
    if (!f) { perror(argv[3]); return 3; }
    fwrite(map[1], 1, szout, f); fclose(f);
    printf("dispatched %u samples\n", N);

    for (int i = 5; i < argc; i++) {
        size_t n2; uint32_t *b2 = slurp(argv[i], &n2);
        VkShaderModuleCreateInfo s2 = { VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO };
        s2.codeSize = n2; s2.pCode = b2;
        VkShaderModule m2; VkResult r2 = vkCreateShaderModule(dev, &s2, NULL, &m2);
        printf("vkCreateShaderModule(real raygen %s, %zu B) -> %d\n", argv[i], n2, r2);
        if (r2 == VK_SUCCESS) vkDestroyShaderModule(dev, m2, NULL);
        free(b2);
        if (r2 != VK_SUCCESS) return 4;
    }
    vkDestroyDevice(dev, NULL); vkDestroyInstance(inst, NULL);
    return 0;
}
